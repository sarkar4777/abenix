#include <curl/curl.h>
#include <dirent.h>
#include <errno.h>
#include <json-c/json.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/time.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

#include "runtime.h"

typedef struct {
    char  *buf;
    size_t len;
    size_t cap;
} sbuf_t;

static size_t curl_collect(void *ptr, size_t s, size_t n, void *user)
{
    size_t add = s * n;
    sbuf_t *b = (sbuf_t *)user;
    if (b->len + add + 1 > b->cap) {
        while (b->len + add + 1 > b->cap) b->cap = b->cap ? b->cap * 2 : 4096;
        b->buf = (char *)realloc(b->buf, b->cap);
    }
    memcpy(b->buf + b->len, ptr, add);
    b->len += add;
    b->buf[b->len] = '\0';
    return add;
}

static long now_ms(void)
{
    struct timeval tv;
    gettimeofday(&tv, NULL);
    return (long)tv.tv_sec * 1000 + tv.tv_usec / 1000;
}

static char *json_escape(const char *s)
{
    size_t cap = strlen(s) * 2 + 16;
    char *o = (char *)malloc(cap);
    size_t k = 0;
    for (const char *p = s; *p; p++) {
        if (k + 8 >= cap) { cap *= 2; o = (char *)realloc(o, cap); }
        unsigned char c = (unsigned char)*p;
        if (c == '"' || c == '\\') { o[k++] = '\\'; o[k++] = (char)c; }
        else if (c == '\n') { o[k++] = '\\'; o[k++] = 'n'; }
        else if (c == '\r') { o[k++] = '\\'; o[k++] = 'r'; }
        else if (c == '\t') { o[k++] = '\\'; o[k++] = 't'; }
        else if (c < 0x20)  { k += snprintf(o + k, cap - k, "\\u%04x", c); }
        else                { o[k++] = (char)c; }
    }
    o[k] = '\0';
    return o;
}

/* run python3 -c "<code>" with a 5-second alarm, return stdout. */
char *code_executor_run(const char *code, int *exit_code, char **err_out)
{
    int outp[2];
    if (pipe(outp) != 0) {
        if (err_out) *err_out = strdup(strerror(errno));
        *exit_code = -1;
        return NULL;
    }
    pid_t pid = fork();
    if (pid < 0) {
        close(outp[0]); close(outp[1]);
        if (err_out) *err_out = strdup("fork failed");
        *exit_code = -1;
        return NULL;
    }
    if (pid == 0) {
        dup2(outp[1], 1);
        dup2(outp[1], 2);
        close(outp[0]); close(outp[1]);
        alarm(5);
        execlp("python3", "python3", "-c", code, (char *)NULL);
        execlp("python", "python", "-c", code, (char *)NULL);
        fprintf(stderr, "exec failed\n");
        _exit(127);
    }
    close(outp[1]);
    sbuf_t out = {0};
    char buf[2048];
    ssize_t n;
    while ((n = read(outp[0], buf, sizeof(buf))) > 0) {
        if (out.len + (size_t)n + 1 > out.cap) {
            while (out.len + (size_t)n + 1 > out.cap) out.cap = out.cap ? out.cap * 2 : 4096;
            out.buf = (char *)realloc(out.buf, out.cap);
        }
        memcpy(out.buf + out.len, buf, (size_t)n);
        out.len += (size_t)n;
        out.buf[out.len] = '\0';
    }
    close(outp[0]);
    int wstatus = 0;
    waitpid(pid, &wstatus, 0);
    if (WIFSIGNALED(wstatus) && WTERMSIG(wstatus) == SIGALRM) {
        if (err_out) *err_out = strdup("code_executor_timeout");
        *exit_code = -2;
    } else {
        *exit_code = WIFEXITED(wstatus) ? WEXITSTATUS(wstatus) : -1;
    }
    return out.buf ? out.buf : strdup("");
}

static char *anthropic_call(const edge_config_t *cfg, const edge_agent_t *agent,
                            const char *user_message, int *http_status)
{
    char base[300];
    strncpy(base, cfg->anthropic_base_url, sizeof(base) - 1);
    base[sizeof(base) - 1] = '\0';
    size_t n = strlen(base);
    while (n > 0 && base[n - 1] == '/') base[--n] = '\0';

    char url[512];
    snprintf(url, sizeof(url), "%s/v1/messages", base);

    char *esc_msg    = json_escape(user_message);
    char *esc_sys    = json_escape(agent->system_prompt);
    size_t bsz = strlen(esc_msg) + strlen(esc_sys) + 1024;
    char *body = (char *)malloc(bsz);
    snprintf(body, bsz,
             "{\"model\":\"%s\",\"max_tokens\":%d,\"temperature\":%g,"
             "\"system\":\"%s\",\"messages\":[{\"role\":\"user\",\"content\":\"%s\"}]}",
             agent->model, agent->max_tokens, agent->temperature,
             esc_sys, esc_msg);
    free(esc_msg); free(esc_sys);

    CURL *c = curl_easy_init();
    if (!c) { free(body); *http_status = -1; return NULL; }
    sbuf_t resp = {0};
    char xkey[300];
    snprintf(xkey, sizeof(xkey), "x-api-key: %s", cfg->anthropic_api_key);
    struct curl_slist *hdrs = NULL;
    hdrs = curl_slist_append(hdrs, xkey);
    hdrs = curl_slist_append(hdrs, "anthropic-version: 2023-06-01");
    hdrs = curl_slist_append(hdrs, "content-type: application/json");
    curl_easy_setopt(c, CURLOPT_URL, url);
    curl_easy_setopt(c, CURLOPT_POSTFIELDS, body);
    curl_easy_setopt(c, CURLOPT_POSTFIELDSIZE, (long)strlen(body));
    curl_easy_setopt(c, CURLOPT_HTTPHEADER, hdrs);
    curl_easy_setopt(c, CURLOPT_WRITEFUNCTION, curl_collect);
    curl_easy_setopt(c, CURLOPT_WRITEDATA, &resp);
    curl_easy_setopt(c, CURLOPT_TIMEOUT, 30L);
    curl_easy_setopt(c, CURLOPT_NOSIGNAL, 1L);
    CURLcode rc = curl_easy_perform(c);
    long status = 0;
    curl_easy_getinfo(c, CURLINFO_RESPONSE_CODE, &status);
    curl_slist_free_all(hdrs);
    curl_easy_cleanup(c);
    free(body);
    *http_status = (int)status;
    if (rc != CURLE_OK) {
        free(resp.buf);
        return NULL;
    }
    return resp.buf;
}

static char *extract_text(const char *json_in)
{
    struct json_object *root = json_tokener_parse(json_in);
    if (!root) return strdup("");
    struct json_object *content = NULL;
    if (!json_object_object_get_ex(root, "content", &content)) {
        json_object_put(root);
        return strdup("");
    }
    size_t n = json_object_array_length(content);
    sbuf_t out = {0};
    for (size_t i = 0; i < n; i++) {
        struct json_object *blk = json_object_array_get_idx(content, i);
        struct json_object *type = NULL, *text = NULL;
        if (json_object_object_get_ex(blk, "type", &type) &&
            strcmp(json_object_get_string(type), "text") == 0 &&
            json_object_object_get_ex(blk, "text", &text)) {
            const char *t = json_object_get_string(text);
            size_t tl = strlen(t);
            if (out.len + tl + 1 > out.cap) {
                while (out.len + tl + 1 > out.cap) out.cap = out.cap ? out.cap * 2 : 4096;
                out.buf = (char *)realloc(out.buf, out.cap);
            }
            memcpy(out.buf + out.len, t, tl);
            out.len += tl;
            out.buf[out.len] = '\0';
        }
    }
    json_object_put(root);
    return out.buf ? out.buf : strdup("");
}

char *agent_execute_json(const edge_config_t *cfg, edge_agent_t *agent,
                         const char *body, size_t body_len)
{
    /* parse body for "message" + optional "code" for code_executor. */
    char *user_message = strdup("");
    char *code = NULL;
    if (body_len > 0 && body) {
        struct json_object *root = json_tokener_parse(body);
        if (root) {
            struct json_object *m = NULL;
            if (json_object_object_get_ex(root, "message", &m)) {
                free(user_message);
                user_message = strdup(json_object_get_string(m));
            }
            struct json_object *params = NULL;
            if (json_object_object_get_ex(root, "params", &params)) {
                struct json_object *cv = NULL;
                if (json_object_object_get_ex(params, "code", &cv)) {
                    code = strdup(json_object_get_string(cv));
                }
            }
            json_object_put(root);
        }
    }

    if ((int)strlen(user_message) > agent->max_payload_bytes) {
        char *err = NULL;
        asprintf(&err, "{\"ok\":false,\"error\":\"payload exceeds %d bytes\"}",
                 agent->max_payload_bytes);
        free(user_message); free(code);
        return err;
    }

    long started = now_ms();
    char *result_json = NULL;

    /* check for local model_weights — not supported in v1.1 (matches Python). */
    char weights[EDGE_MAX_PATH * 2];
    snprintf(weights, sizeof(weights), "%s/model_weights", agent->dir);
    struct stat st;
    int has_weights = 0;
    if (stat(weights, &st) == 0 && S_ISDIR(st.st_mode)) {
        DIR *d = opendir(weights);
        if (d) {
            struct dirent *de;
            while ((de = readdir(d)) != NULL) {
                if (de->d_name[0] != '.') { has_weights = 1; break; }
            }
            closedir(d);
        }
    }
    if (has_weights) {
        result_json = strdup(
            "{\"ok\":false,\"error\":\"local model_weights present but no local "
            "inference shipped in v1.1\",\"phase_2\":true}");
    } else if (code && *code) {
        /* code_executor path. */
        int has_ce = 0;
        for (int i = 0; i < agent->tool_count; i++) {
            if (strcmp(agent->tools[i], "code_executor") == 0) { has_ce = 1; break; }
        }
        if (!has_ce) {
            result_json = strdup(
                "{\"ok\":false,\"error\":\"code_executor not in tool whitelist\"}");
        } else {
            int rc = 0;
            char *err = NULL;
            char *out = code_executor_run(code, &rc, &err);
            char *esc_out = json_escape(out ? out : "");
            char *esc_err = err ? json_escape(err) : NULL;
            asprintf(&result_json,
                     "{\"ok\":%s,\"exit_code\":%d,\"stdout\":\"%s\"%s%s%s}",
                     rc == 0 ? "true" : "false", rc, esc_out,
                     esc_err ? ",\"error\":\"" : "",
                     esc_err ? esc_err : "",
                     esc_err ? "\"" : "");
            free(out); free(err); free(esc_out); free(esc_err);
        }
    } else if (!cfg->anthropic_api_key[0]) {
        char *esc = json_escape(user_message);
        asprintf(&result_json,
                 "{\"ok\":false,\"error\":\"ANTHROPIC_API_KEY not configured on "
                 "edge runtime\",\"stub\":true,\"echo\":\"%s\"}", esc);
        free(esc);
    } else {
        int status = 0;
        char *raw = anthropic_call(cfg, agent, user_message, &status);
        if (raw && status >= 200 && status < 300) {
            char *txt = extract_text(raw);
            char *esc = json_escape(txt);
            asprintf(&result_json,
                     "{\"ok\":true,\"text\":\"%s\"}", esc);
            free(txt); free(esc);
        } else {
            char *esc = json_escape(raw ? raw : "no response");
            asprintf(&result_json,
                     "{\"ok\":false,\"error\":\"anthropic_failed status=%d\","
                     "\"raw\":\"%s\"}", status, esc);
            free(esc);
        }
        free(raw);
    }

    long duration = now_ms() - started;
    char *full = NULL;
    asprintf(&full,
             "{\"slug\":\"%s\",\"digest\":\"%s\",\"duration_ms\":%ld,"
             "\"result\":%s}",
             agent->slug, agent->digest_hex, duration, result_json);
    free(result_json);
    free(user_message);
    free(code);
    return full;
}
