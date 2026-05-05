#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <unistd.h>
#include <zlib.h>

#include <openssl/bio.h>
#include <openssl/err.h>
#include <openssl/evp.h>
#include <openssl/pem.h>
#include <openssl/rsa.h>
#include <openssl/sha.h>

#include "runtime.h"

/* tar header (ustar) — 512 bytes, name at offset 0 (100), size at 124 (12 octal). */
#define TAR_BLOCK 512

static int read_file_all(const char *path, unsigned char **out, size_t *out_len)
{
    *out = NULL;
    *out_len = 0;
    FILE *fp = fopen(path, "rb");
    if (!fp) return -1;
    if (fseek(fp, 0, SEEK_END) != 0) { fclose(fp); return -1; }
    long sz = ftell(fp);
    if (sz < 0) { fclose(fp); return -1; }
    if (fseek(fp, 0, SEEK_SET) != 0) { fclose(fp); return -1; }
    unsigned char *buf = (unsigned char *)malloc((size_t)sz);
    if (!buf) { fclose(fp); return -1; }
    size_t n = fread(buf, 1, (size_t)sz, fp);
    fclose(fp);
    if (n != (size_t)sz) { free(buf); return -1; }
    *out = buf;
    *out_len = n;
    return 0;
}

static int looks_like_gzip(const unsigned char *b, size_t n)
{
    return n >= 2 && b[0] == 0x1f && b[1] == 0x8b;
}

static int gunzip_buffer(const unsigned char *in, size_t in_len,
                        unsigned char **out, size_t *out_len)
{
    z_stream z;
    memset(&z, 0, sizeof(z));
    if (inflateInit2(&z, 15 + 32) != Z_OK) return -1;
    size_t cap = in_len * 4 + 4096;
    unsigned char *buf = (unsigned char *)malloc(cap);
    if (!buf) { inflateEnd(&z); return -1; }
    z.next_in = (unsigned char *)in;
    z.avail_in = (uInt)in_len;
    z.next_out = buf;
    z.avail_out = (uInt)cap;
    int rc;
    for (;;) {
        rc = inflate(&z, Z_NO_FLUSH);
        if (rc == Z_STREAM_END) break;
        if (rc != Z_OK) {
            inflateEnd(&z);
            free(buf);
            return -1;
        }
        if (z.avail_out == 0) {
            size_t used = (size_t)(z.next_out - buf);
            cap *= 2;
            unsigned char *nb = (unsigned char *)realloc(buf, cap);
            if (!nb) { inflateEnd(&z); free(buf); return -1; }
            buf = nb;
            z.next_out = buf + used;
            z.avail_out = (uInt)(cap - used);
        }
    }
    size_t used = (size_t)(z.next_out - buf);
    inflateEnd(&z);
    *out = buf;
    *out_len = used;
    return 0;
}

static long parse_octal(const char *s, size_t n)
{
    long v = 0;
    for (size_t i = 0; i < n && s[i]; i++) {
        if (s[i] < '0' || s[i] > '7') break;
        v = v * 8 + (s[i] - '0');
    }
    return v;
}

/* iterate tar headers; for each entry, name + offset+len of content. */
typedef struct {
    char     name[256];
    size_t   header_off;
    size_t   data_off;
    size_t   data_len;
    size_t   total_blocks;
} tar_entry_t;

static int iter_tar(const unsigned char *buf, size_t buf_len,
                    tar_entry_t **out_entries, size_t *out_count)
{
    *out_entries = NULL;
    *out_count = 0;
    size_t cap = 32, n = 0;
    tar_entry_t *arr = (tar_entry_t *)calloc(cap, sizeof(*arr));
    if (!arr) return -1;
    size_t off = 0;
    while (off + TAR_BLOCK <= buf_len) {
        const unsigned char *h = buf + off;
        int empty = 1;
        for (int i = 0; i < TAR_BLOCK; i++) {
            if (h[i] != 0) { empty = 0; break; }
        }
        if (empty) break;
        long sz = parse_octal((const char *)(h + 124), 12);
        if (sz < 0) { free(arr); return -1; }
        size_t blocks = ((size_t)sz + TAR_BLOCK - 1) / TAR_BLOCK;

        if (n == cap) {
            cap *= 2;
            tar_entry_t *na = (tar_entry_t *)realloc(arr, cap * sizeof(*arr));
            if (!na) { free(arr); return -1; }
            arr = na;
            memset(arr + n, 0, (cap - n) * sizeof(*arr));
        }
        memcpy(arr[n].name, h, 100);
        arr[n].name[255] = '\0';
        arr[n].header_off = off;
        arr[n].data_off = off + TAR_BLOCK;
        arr[n].data_len = (size_t)sz;
        arr[n].total_blocks = 1 + blocks;
        n++;
        off += TAR_BLOCK + blocks * TAR_BLOCK;
    }
    *out_entries = arr;
    *out_count = n;
    return 0;
}

static int find_signature(const tar_entry_t *entries, size_t n, size_t *idx)
{
    for (size_t i = 0; i < n; i++) {
        if (strcmp(entries[i].name, "signature.sig") == 0) {
            *idx = i;
            return 0;
        }
    }
    return -1;
}

/* concatenate everything in tar except the signature entry's blocks. */
static int build_unsigned_view(const unsigned char *buf, size_t buf_len,
                               const tar_entry_t *entries, size_t n_entries,
                               size_t sig_idx,
                               unsigned char **out, size_t *out_len)
{
    size_t sig_start = entries[sig_idx].header_off;
    size_t sig_end = sig_start + entries[sig_idx].total_blocks * TAR_BLOCK;
    size_t out_cap = buf_len;
    unsigned char *o = (unsigned char *)malloc(out_cap);
    if (!o) return -1;
    size_t pos = 0;
    if (sig_start > 0) {
        memcpy(o + pos, buf, sig_start);
        pos += sig_start;
    }
    if (sig_end < buf_len) {
        memcpy(o + pos, buf + sig_end, buf_len - sig_end);
        pos += buf_len - sig_end;
    }
    *out = o;
    *out_len = pos;
    return 0;
}

static EVP_PKEY *load_pubkey(const char *path)
{
    FILE *fp = fopen(path, "r");
    if (!fp) return NULL;
    EVP_PKEY *k = PEM_read_PUBKEY(fp, NULL, NULL, NULL);
    fclose(fp);
    return k;
}

static int verify_pss(EVP_PKEY *pubkey,
                      const unsigned char *data, size_t data_len,
                      const unsigned char *sig, size_t sig_len)
{
    EVP_MD_CTX *ctx = EVP_MD_CTX_new();
    if (!ctx) return -1;
    EVP_PKEY_CTX *pctx = NULL;
    if (EVP_DigestVerifyInit(ctx, &pctx, EVP_sha256(), NULL, pubkey) <= 0) {
        EVP_MD_CTX_free(ctx);
        return -1;
    }
    if (EVP_PKEY_CTX_set_rsa_padding(pctx, RSA_PKCS1_PSS_PADDING) <= 0) {
        EVP_MD_CTX_free(ctx);
        return -1;
    }
    if (EVP_PKEY_CTX_set_rsa_pss_saltlen(pctx, 32) <= 0) {
        EVP_MD_CTX_free(ctx);
        return -1;
    }
    if (EVP_PKEY_CTX_set_rsa_mgf1_md(pctx, EVP_sha256()) <= 0) {
        EVP_MD_CTX_free(ctx);
        return -1;
    }
    if (EVP_DigestVerifyUpdate(ctx, data, data_len) <= 0) {
        EVP_MD_CTX_free(ctx);
        return -1;
    }
    int rc = EVP_DigestVerifyFinal(ctx, sig, sig_len);
    EVP_MD_CTX_free(ctx);
    return rc == 1 ? 0 : -1;
}

static void sha256_hex(const unsigned char *buf, size_t n, char out[65])
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

static int safe_path(const char *name)
{
    if (!name || !*name) return 0;
    if (name[0] == '/') return 0;
    if (strstr(name, "..")) return 0;
    return 1;
}

static int rmrf(const char *path)
{
    /* shell out for portability — bundle dir is small. */
    char cmd[EDGE_MAX_PATH + 32];
    snprintf(cmd, sizeof(cmd), "rm -rf '%s'", path);
    int rc = system(cmd);
    return rc;
}

static void mkdir_p_dest(const char *path)
{
    char tmp[EDGE_MAX_PATH];
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

static int extract_to_dir(const unsigned char *buf, size_t buf_len,
                          const tar_entry_t *entries, size_t n,
                          const char *dest)
{
    rmrf(dest);
    mkdir_p_dest(dest);
    for (size_t i = 0; i < n; i++) {
        const tar_entry_t *e = &entries[i];
        if (strcmp(e->name, "signature.sig") == 0) continue;
        if (!safe_path(e->name)) {
            edge_log("ERROR", "unsafe_path name=%s", e->name);
            return -1;
        }
        char full[EDGE_MAX_PATH * 2];
        snprintf(full, sizeof(full), "%s/%s", dest, e->name);
        size_t fl = strlen(e->name);
        if (fl > 0 && e->name[fl - 1] == '/') {
            mkdir_p_dest(full);
            continue;
        }
        /* ensure parent dir exists. */
        char parent[EDGE_MAX_PATH * 2];
        strncpy(parent, full, sizeof(parent) - 1);
        parent[sizeof(parent) - 1] = '\0';
        char *slash = strrchr(parent, '/');
        if (slash) {
            *slash = '\0';
            mkdir_p_dest(parent);
        }
        FILE *fp = fopen(full, "wb");
        if (!fp) {
            edge_log("ERROR", "extract_open_failed path=%s err=%s", full, strerror(errno));
            return -1;
        }
        if (e->data_len > 0) {
            if (e->data_off + e->data_len > buf_len) { fclose(fp); return -1; }
            fwrite(buf + e->data_off, 1, e->data_len, fp);
        }
        fclose(fp);
    }
    return 0;
}

static int find_entry(const tar_entry_t *entries, size_t n, const char *name)
{
    for (size_t i = 0; i < n; i++) {
        if (strcmp(entries[i].name, name) == 0) return (int)i;
    }
    return -1;
}

int bundle_install_from_file(edge_registry_t *r, const edge_config_t *cfg,
                             const char *bundle_path, edge_agent_t *out)
{
    unsigned char *raw = NULL;
    size_t raw_len = 0;
    if (read_file_all(bundle_path, &raw, &raw_len) != 0) {
        edge_log("ERROR", "bundle_read_failed path=%s", bundle_path);
        return -1;
    }

    /* full-bundle digest for log + reporting (matches Python sha256(bundle_bytes)). */
    char digest[65];
    sha256_hex(raw, raw_len, digest);

    unsigned char *tar_bytes = raw;
    size_t tar_len = raw_len;
    unsigned char *gun = NULL;
    if (looks_like_gzip(raw, raw_len)) {
        if (gunzip_buffer(raw, raw_len, &gun, &tar_len) != 0) {
            edge_log("ERROR", "bundle_gunzip_failed");
            free(raw);
            return -1;
        }
        tar_bytes = gun;
    }

    tar_entry_t *entries = NULL;
    size_t n_entries = 0;
    if (iter_tar(tar_bytes, tar_len, &entries, &n_entries) != 0 || n_entries == 0) {
        edge_log("ERROR", "bundle_tar_parse_failed");
        free(raw); free(gun);
        return -1;
    }

    size_t sig_idx = 0;
    int has_sig = (find_signature(entries, n_entries, &sig_idx) == 0);

    EVP_PKEY *pubkey = load_pubkey(cfg->signing_pubkey_path);
    if (pubkey) {
        if (!has_sig) {
            edge_log("ERROR", "bundle_missing_signature");
            EVP_PKEY_free(pubkey);
            free(entries); free(raw); free(gun);
            return -1;
        }
        unsigned char *unsigned_view = NULL;
        size_t uv_len = 0;
        if (build_unsigned_view(tar_bytes, tar_len, entries, n_entries,
                                sig_idx, &unsigned_view, &uv_len) != 0) {
            EVP_PKEY_free(pubkey);
            free(entries); free(raw); free(gun);
            return -1;
        }
        const unsigned char *sig_data = tar_bytes + entries[sig_idx].data_off;
        size_t sig_len = entries[sig_idx].data_len;
        int vrc = verify_pss(pubkey, unsigned_view, uv_len, sig_data, sig_len);
        free(unsigned_view);
        EVP_PKEY_free(pubkey);
        if (vrc != 0) {
            edge_log("ERROR", "bundle_signature_invalid");
            free(entries); free(raw); free(gun);
            return -1;
        }
    } else {
        edge_log("WARN", "no signing pubkey configured -- accepting bundle UNVERIFIED");
    }

    int mi = find_entry(entries, n_entries, "agent.yaml");
    if (mi < 0) {
        edge_log("ERROR", "bundle_missing_agent_yaml");
        free(entries); free(raw); free(gun);
        return -1;
    }

    edge_agent_t agent;
    memset(&agent, 0, sizeof(agent));
    if (manifest_parse_yaml((const char *)(tar_bytes + entries[mi].data_off),
                            entries[mi].data_len, &agent) != 0) {
        edge_log("ERROR", "manifest_parse_failed");
        free(entries); free(raw); free(gun);
        return -1;
    }
    if (manifest_validate(&agent) != 0) {
        edge_log("ERROR", "manifest_validate_failed slug=%s", agent.slug);
        free(entries); free(raw); free(gun);
        return -1;
    }

    snprintf(agent.dir, sizeof(agent.dir), "%s/%s", cfg->bundle_dir, agent.slug);
    if (extract_to_dir(tar_bytes, tar_len, entries, n_entries, agent.dir) != 0) {
        free(entries); free(raw); free(gun);
        return -1;
    }

    /* read system_prompt.md from disk. */
    char prompt_path[EDGE_MAX_PATH * 2];
    snprintf(prompt_path, sizeof(prompt_path), "%s/system_prompt.md", agent.dir);
    FILE *fp = fopen(prompt_path, "rb");
    if (fp) {
        size_t rd = fread(agent.system_prompt, 1, sizeof(agent.system_prompt) - 1, fp);
        agent.system_prompt[rd] = '\0';
        fclose(fp);
    }

    memcpy(agent.digest_hex, digest, 65);
    agent.digest_hex[65] = '\0';

    if (registry_install(r, &agent) != 0) {
        edge_log("ERROR", "registry_install_failed slug=%s", agent.slug);
        free(entries); free(raw); free(gun);
        return -1;
    }
    edge_log("INFO", "agent_loaded slug=%s digest=%s", agent.slug, agent.digest_hex);
    if (out) memcpy(out, &agent, sizeof(agent));

    free(entries);
    free(raw);
    free(gun);
    return 0;
}
