#include <errno.h>
#include <fcntl.h>
#include <ftw.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <time.h>
#include <unistd.h>

#include <openssl/bio.h>
#include <openssl/err.h>
#include <openssl/evp.h>
#include <openssl/pem.h>
#include <openssl/rsa.h>
#include <openssl/sha.h>

#include "runtime.h"

#define TAR_BLOCK 512

/* one install at a time, the swap and the registry update belong together */
static pthread_mutex_t g_install = PTHREAD_MUTEX_INITIALIZER;

static int read_file_all(const char *path, unsigned char **out, size_t *out_len)
{
    *out = NULL;
    *out_len = 0;
    FILE *fp = fopen(path, "rb");
    if (!fp) return -1;
    if (fseek(fp, 0, SEEK_END) != 0) { fclose(fp); return -1; }
    long sz = ftell(fp);
    if (sz < 0 || sz > EDGE_MAX_BUNDLE_BYTES) { fclose(fp); return -1; }
    if (fseek(fp, 0, SEEK_SET) != 0) { fclose(fp); return -1; }
    unsigned char *buf = (unsigned char *)malloc((size_t)sz + 1);
    if (!buf) { fclose(fp); return -1; }
    size_t n = fread(buf, 1, (size_t)sz, fp);
    fclose(fp);
    if (n != (size_t)sz) { free(buf); return -1; }
    *out = buf;
    *out_len = n;
    return 0;
}

static long parse_octal(const unsigned char *s, size_t n)
{
    long v = 0;
    size_t i = 0;
    while (i < n && s[i] == ' ') i++;
    for (; i < n && s[i]; i++) {
        if (s[i] < '0' || s[i] > '7') {
            if (s[i] == ' ') break;
            return -1;
        }
        if (v > (1L << 40)) return -1;
        v = v * 8 + (s[i] - '0');
    }
    return v;
}

typedef struct {
    char     name[101];
    char     type;
    size_t   header_off;
    size_t   data_off;
    size_t   data_len;
    size_t   total_blocks;
} tar_entry_t;

static int header_checksum_ok(const unsigned char *h)
{
    long want = parse_octal(h + 148, 8);
    long sum = 0;
    for (int i = 0; i < TAR_BLOCK; i++) {
        sum += (i >= 148 && i < 156) ? ' ' : h[i];
    }
    return want == sum;
}

static int safe_path(const char *name)
{
    if (!name[0] || name[0] == '/' || strchr(name, '\\')) return 0;
    const char *p = name;
    while (*p) {
        const char *slash = strchr(p, '/');
        size_t len = slash ? (size_t)(slash - p) : strlen(p);
        if (len == 2 && p[0] == '.' && p[1] == '.') return 0;
        if (!slash) break;
        p = slash + 1;
    }
    return 1;
}

/* plain files and folders under safe relative names only, anything else refuses the bundle */
static int iter_tar(const unsigned char *buf, size_t buf_len,
                    tar_entry_t **out_entries, size_t *out_count,
                    char *err, size_t err_cap)
{
    *out_entries = NULL;
    *out_count = 0;
    tar_entry_t *arr = (tar_entry_t *)calloc(EDGE_MAX_BUNDLE_MEMBERS, sizeof(*arr));
    if (!arr) return -1;
    size_t n = 0, off = 0;
    while (off + TAR_BLOCK <= buf_len) {
        const unsigned char *h = buf + off;
        int empty = 1;
        for (int i = 0; i < TAR_BLOCK; i++) {
            if (h[i] != 0) { empty = 0; break; }
        }
        if (empty) break;
        if (n == EDGE_MAX_BUNDLE_MEMBERS) {
            snprintf(err, err_cap, "bundle has too many entries");
            free(arr);
            return -1;
        }
        if (!header_checksum_ok(h)) {
            snprintf(err, err_cap, "bundle is not a readable tar file");
            free(arr);
            return -1;
        }
        long sz = parse_octal(h + 124, 12);
        if (sz < 0 || (size_t)sz > buf_len || off + TAR_BLOCK + (size_t)sz > buf_len) {
            snprintf(err, err_cap, "bundle entry runs past the end of the file");
            free(arr);
            return -1;
        }
        size_t blocks = ((size_t)sz + TAR_BLOCK - 1) / TAR_BLOCK;
        tar_entry_t *e = &arr[n];
        memcpy(e->name, h, 100);
        e->name[100] = '\0';
        e->type = (char)h[156];
        if (e->type != '0' && e->type != '\0' && e->type != '5') {
            snprintf(err, err_cap, "bundle entry %.100s is a link or device, refused", e->name);
            free(arr);
            return -1;
        }
        /* a ustar prefix would make the real path longer than the name checked here */
        if (memcmp(h + 257, "ustar\0", 6) == 0 && h[345] != 0) {
            snprintf(err, err_cap, "unsafe path in bundle, long names are refused");
            free(arr);
            return -1;
        }
        if (!safe_path(e->name)) {
            snprintf(err, err_cap, "unsafe path in bundle %.100s", e->name);
            free(arr);
            return -1;
        }
        for (size_t i = 0; i < n; i++) {
            if (strcmp(arr[i].name, e->name) == 0) {
                snprintf(err, err_cap, "duplicate entry in bundle %.100s", e->name);
                free(arr);
                return -1;
            }
        }
        e->header_off = off;
        e->data_off = off + TAR_BLOCK;
        e->data_len = (size_t)sz;
        e->total_blocks = 1 + blocks;
        n++;
        off += TAR_BLOCK + blocks * TAR_BLOCK;
    }
    *out_entries = arr;
    *out_count = n;
    return 0;
}

static int find_entry(const tar_entry_t *entries, size_t n, const char *name)
{
    for (size_t i = 0; i < n; i++) {
        if (strcmp(entries[i].name, name) == 0) return (int)i;
    }
    return -1;
}

/* the received bytes with the signature entry cut out, which is what the platform signs */
static int build_unsigned_view(const unsigned char *buf, size_t buf_len,
                               const tar_entry_t *sig,
                               unsigned char **out, size_t *out_len)
{
    size_t start = sig->header_off;
    size_t end = start + sig->total_blocks * TAR_BLOCK;
    if (end > buf_len) end = buf_len;
    unsigned char *o = (unsigned char *)malloc(buf_len + 1);
    if (!o) return -1;
    memcpy(o, buf, start);
    memcpy(o + start, buf + end, buf_len - end);
    *out = o;
    *out_len = start + (buf_len - end);
    return 0;
}

static EVP_PKEY *load_pubkey(const edge_config_t *cfg, int *present)
{
    *present = 0;
    if (cfg->signing_pubkey_pem[0]) {
        *present = 1;
        BIO *bio = BIO_new_mem_buf(cfg->signing_pubkey_pem, -1);
        if (!bio) return NULL;
        EVP_PKEY *k = PEM_read_bio_PUBKEY(bio, NULL, NULL, NULL);
        BIO_free(bio);
        return k;
    }
    struct stat st;
    if (stat(cfg->signing_pubkey_path, &st) != 0 || st.st_size == 0) return NULL;
    *present = 1;
    FILE *fp = fopen(cfg->signing_pubkey_path, "r");
    if (!fp) return NULL;
    EVP_PKEY *k = PEM_read_PUBKEY(fp, NULL, NULL, NULL);
    fclose(fp);
    return k;
}

/* 1 a usable key, 0 none set, -1 set but unusable */
int bundle_pubkey_state(const edge_config_t *cfg)
{
    int present = 0;
    EVP_PKEY *k = load_pubkey(cfg, &present);
    if (k) {
        EVP_PKEY_free(k);
        return 1;
    }
    return present ? -1 : 0;
}

static int verify_pss(EVP_PKEY *pubkey,
                      const unsigned char *data, size_t data_len,
                      const unsigned char *sig, size_t sig_len)
{
    EVP_MD_CTX *ctx = EVP_MD_CTX_new();
    if (!ctx) return -1;
    EVP_PKEY_CTX *pctx = NULL;
    int ok = EVP_DigestVerifyInit(ctx, &pctx, EVP_sha256(), NULL, pubkey) > 0 &&
             EVP_PKEY_CTX_set_rsa_padding(pctx, RSA_PKCS1_PSS_PADDING) > 0 &&
             EVP_PKEY_CTX_set_rsa_pss_saltlen(pctx, 32) > 0 &&
             EVP_PKEY_CTX_set_rsa_mgf1_md(pctx, EVP_sha256()) > 0 &&
             EVP_DigestVerifyUpdate(ctx, data, data_len) > 0 &&
             EVP_DigestVerifyFinal(ctx, sig, sig_len) == 1;
    EVP_MD_CTX_free(ctx);
    return ok ? 0 : -1;
}

void bundle_digest_hex(const unsigned char *buf, size_t n, char out[65])
{
    unsigned char d[SHA256_DIGEST_LENGTH];
    SHA256(buf, n, d);
    static const char hex[] = "0123456789abcdef";
    for (int i = 0; i < SHA256_DIGEST_LENGTH; i++) {
        out[i * 2]     = hex[(d[i] >> 4) & 0xf];
        out[i * 2 + 1] = hex[d[i] & 0xf];
    }
    out[64] = '\0';
}

int edge_valid_slug(const char *slug)
{
    size_t n = strlen(slug);
    if (n == 0 || n > 95 || strstr(slug, "..")) return 0;
    for (size_t i = 0; i < n; i++) {
        char c = slug[i];
        int alnum = (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9');
        if (i == 0 ? !alnum : !(alnum || c == '.' || c == '_' || c == '-')) return 0;
    }
    return 1;
}

static int rm_entry(const char *path, const struct stat *st, int kind, struct FTW *ftw)
{
    (void)st; (void)kind; (void)ftw;
    return remove(path);
}

/* no shell and no following of links */
int edge_rm_rf(const char *path)
{
    struct stat st;
    if (lstat(path, &st) != 0) return errno == ENOENT ? 0 : -1;
    return nftw(path, rm_entry, 16, FTW_DEPTH | FTW_PHYS);
}

static void mkdir_p(const char *path)
{
    char tmp[EDGE_MAX_PATH * 2];
    strncpy(tmp, path, sizeof(tmp) - 1);
    tmp[sizeof(tmp) - 1] = '\0';
    size_t n = strlen(tmp);
    for (size_t i = 1; i < n; i++) {
        if (tmp[i] == '/') {
            tmp[i] = '\0';
            mkdir(tmp, 0755);
            tmp[i] = '/';
        }
    }
    mkdir(tmp, 0755);
}

static int write_file(const char *path, const unsigned char *data, size_t len)
{
    /* O_EXCL refuses to write through anything that already sits at this name */
    int fd = open(path, O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW, 0644);
    if (fd < 0) return -1;
    size_t done = 0;
    while (done < len) {
        ssize_t w = write(fd, data + done, len - done);
        if (w <= 0) { close(fd); return -1; }
        done += (size_t)w;
    }
    return close(fd);
}

/* writes beside the live folder and swaps, so a failed install leaves the old agent serving */
static int extract_and_swap(const unsigned char *raw, size_t raw_len,
                            const tar_entry_t *entries, size_t n,
                            const edge_config_t *cfg, const char *slug,
                            const char *dest, char *err, size_t err_cap)
{
    char staging[EDGE_MAX_PATH * 2];
    char old[EDGE_MAX_PATH * 2];
    long stamp = (long)time(NULL);
    snprintf(staging, sizeof(staging), "%s/.staging-%s-%d-%ld", cfg->bundle_dir, slug, (int)getpid(), stamp);
    snprintf(old, sizeof(old), "%s/.old-%s-%d-%ld", cfg->bundle_dir, slug, (int)getpid(), stamp);
    edge_rm_rf(staging);
    mkdir_p(cfg->bundle_dir);
    if (mkdir(staging, 0755) != 0) {
        snprintf(err, err_cap, "could not write the bundle folder");
        return -1;
    }
    for (size_t i = 0; i < n; i++) {
        const tar_entry_t *e = &entries[i];
        if (strcmp(e->name, "signature.sig") == 0) continue;
        char full[EDGE_MAX_PATH * 3];
        snprintf(full, sizeof(full), "%s/%s", staging, e->name);
        if (e->type == '5') {
            mkdir_p(full);
            continue;
        }
        char parent[EDGE_MAX_PATH * 3];
        snprintf(parent, sizeof(parent), "%s", full);
        char *slash = strrchr(parent, '/');
        if (slash) {
            *slash = '\0';
            mkdir_p(parent);
        }
        if (write_file(full, raw + e->data_off, e->data_len) != 0) {
            snprintf(err, err_cap, "could not write bundle entry %.100s", e->name);
            edge_rm_rf(staging);
            return -1;
        }
    }
    char saved[EDGE_MAX_PATH * 3];
    snprintf(saved, sizeof(saved), "%s/" EDGE_SAVED_BUNDLE, staging);
    remove(saved);
    if (write_file(saved, raw, raw_len) != 0) {
        snprintf(err, err_cap, "could not save the bundle");
        edge_rm_rf(staging);
        return -1;
    }
    struct stat st;
    int had_old = stat(dest, &st) == 0;
    if (had_old && rename(dest, old) != 0) {
        snprintf(err, err_cap, "could not replace the old agent folder");
        edge_rm_rf(staging);
        return -1;
    }
    if (rename(staging, dest) != 0) {
        if (had_old) rename(old, dest);
        snprintf(err, err_cap, "could not put the new agent folder in place");
        edge_rm_rf(staging);
        return -1;
    }
    if (had_old) edge_rm_rf(old);
    return 0;
}

static int check_signature(const edge_config_t *cfg,
                           const unsigned char *raw, size_t raw_len,
                           const tar_entry_t *entries, size_t n,
                           char *err, size_t err_cap)
{
    int si = find_entry(entries, n, "signature.sig");
    if (si < 0 && !cfg->allow_unsigned) {
        snprintf(err, err_cap,
                 "bundle is unsigned, no signature.sig. Refusing to load, set EDGE_ALLOW_UNSIGNED=true only for local development");
        return -1;
    }
    int present = 0;
    EVP_PKEY *pubkey = load_pubkey(cfg, &present);
    if (si >= 0 && pubkey) {
        unsigned char *view = NULL;
        size_t view_len = 0;
        int rc = build_unsigned_view(raw, raw_len, &entries[si], &view, &view_len);
        if (rc == 0) {
            rc = verify_pss(pubkey, view, view_len, raw + entries[si].data_off, entries[si].data_len);
        }
        free(view);
        EVP_PKEY_free(pubkey);
        if (rc != 0) {
            snprintf(err, err_cap, "bundle_signature_invalid");
            return -1;
        }
        return 0;
    }
    if (pubkey) EVP_PKEY_free(pubkey);
    if (!cfg->allow_unsigned) {
        snprintf(err, err_cap,
                 "no signing public key configured, cannot verify bundle. Set SIGNING_PUBKEY_PEM or SIGNING_PUBKEY_PATH");
        return -1;
    }
    edge_log("WARN", "accepting UNVERIFIED bundle because EDGE_ALLOW_UNSIGNED=true, development only");
    return 0;
}

int bundle_install_bytes(edge_registry_t *r, const edge_config_t *cfg,
                         const unsigned char *raw, size_t raw_len,
                         const char *expected_slug, edge_agent_t *out,
                         char *err, size_t err_cap)
{
    if (raw_len > EDGE_MAX_BUNDLE_BYTES) {
        snprintf(err, err_cap, "bundle is over %d bytes", EDGE_MAX_BUNDLE_BYTES);
        return -1;
    }
    tar_entry_t *entries = NULL;
    size_t n = 0;
    if (iter_tar(raw, raw_len, &entries, &n, err, err_cap) != 0) {
        if (!err[0]) snprintf(err, err_cap, "bundle is not a readable tar file");
        return -1;
    }
    if (n == 0) {
        snprintf(err, err_cap, "bundle is not a readable tar file");
        free(entries);
        return -1;
    }
    int rc = -1;
    static edge_agent_t agent;
    pthread_mutex_lock(&g_install);
    memset(&agent, 0, sizeof(agent));
    do {
        if (check_signature(cfg, raw, raw_len, entries, n, err, err_cap) != 0) break;
        int mi = find_entry(entries, n, "agent.yaml");
        if (mi < 0) {
            snprintf(err, err_cap, "bundle missing agent.yaml");
            break;
        }
        if (manifest_parse_yaml((const char *)(raw + entries[mi].data_off),
                                entries[mi].data_len, &agent) != 0) {
            snprintf(err, err_cap, "agent.yaml is not readable or misses required fields");
            break;
        }
        if (manifest_validate(&agent, err, err_cap) != 0) break;
        if (cfg->tenant_id[0] && strcmp(agent.tenant_id, cfg->tenant_id) != 0) {
            edge_log("ERROR", "bundle_tenant_mismatch slug=%s bundle_tenant=%s runtime_tenant=%s",
                     agent.slug, agent.tenant_id[0] ? agent.tenant_id : "<none>", cfg->tenant_id);
            snprintf(err, err_cap, "bundle tenant_id %s does not match runtime TENANT_ID %s",
                     agent.tenant_id[0] ? agent.tenant_id : "<none>", cfg->tenant_id);
            break;
        }
        if (expected_slug && strcmp(expected_slug, agent.slug) != 0) {
            snprintf(err, err_cap, "bundle is for agent %s, it was sent to %.96s", agent.slug, expected_slug);
            break;
        }
        char digest[65];
        bundle_digest_hex(raw, raw_len, digest);
        static edge_agent_t current;
        if (registry_get(r, agent.slug, &current) && strcmp(current.digest_hex, digest) == 0) {
            if (out) *out = current;
            rc = 0;
            break;
        }
        snprintf(agent.dir, sizeof(agent.dir), "%s/%s", cfg->bundle_dir, agent.slug);
        if (extract_and_swap(raw, raw_len, entries, n, cfg, agent.slug, agent.dir, err, err_cap) != 0) break;

        char prompt_path[EDGE_MAX_PATH * 2];
        snprintf(prompt_path, sizeof(prompt_path), "%s/system_prompt.md", agent.dir);
        FILE *fp = fopen(prompt_path, "rb");
        if (fp) {
            size_t rd = fread(agent.system_prompt, 1, sizeof(agent.system_prompt) - 1, fp);
            agent.system_prompt[rd] = '\0';
            if (fgetc(fp) != EOF) {
                edge_log("WARN", "system_prompt_cut slug=%s the C runtime keeps the first %zu bytes", agent.slug, rd);
            }
            fclose(fp);
        }
        snprintf(agent.digest_hex, sizeof(agent.digest_hex), "%s", digest);
        if (registry_install(r, &agent) != 0) {
            snprintf(err, err_cap, "this gateway already holds %d agents", EDGE_MAX_AGENTS);
            break;
        }
        edge_log("INFO", "agent_loaded slug=%s digest=%s", agent.slug, agent.digest_hex);
        if (out) *out = agent;
        rc = 0;
    } while (0);
    pthread_mutex_unlock(&g_install);
    free(entries);
    if (rc != 0) edge_log("ERROR", "bundle_rejected reason=%s", err);
    return rc;
}

int bundle_install_from_file(edge_registry_t *r, const edge_config_t *cfg,
                             const char *bundle_path, const char *expected_slug,
                             edge_agent_t *out, char *err, size_t err_cap)
{
    unsigned char *raw = NULL;
    size_t raw_len = 0;
    if (read_file_all(bundle_path, &raw, &raw_len) != 0) {
        snprintf(err, err_cap, "could not read the bundle file");
        return -1;
    }
    int rc = bundle_install_bytes(r, cfg, raw, raw_len, expected_slug, out, err, err_cap);
    free(raw);
    return rc;
}
