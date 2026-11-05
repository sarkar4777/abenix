#include <curl/curl.h>
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <json-c/json.h>
#include <poll.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/resource.h>
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

static void sbuf_add(sbuf_t *b, const char *p, size_t add)
{
    if (b->len + add + 1 > b->cap) {
        while (b->len + add + 1 > b->cap) b->cap = b->cap ? b->cap * 2 : 4096;
        b->buf = (char *)realloc(b->buf, b->cap);
    }
    memcpy(b->buf + b->len, p, add);
    b->len += add;
    b->buf[b->len] = '\0';
}

static size_t curl_collect(void *ptr, size_t s, size_t n, void *user)
{
    sbuf_add((sbuf_t *)user, (const char *)ptr, s * n);
    return s * n;
}

static long now_ms(void)
{
    struct timeval tv;
    gettimeofday(&tv, NULL);
    return (long)tv.tv_sec * 1000 + tv.tv_usec / 1000;
}

char *edge_json_escape(const char *s)
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
        else if (c < 0x20)  { k += (size_t)snprintf(o + k, cap - k, "\\u%04x", c); }
        else                { o[k++] = (char)c; }
    }
    o[k] = '\0';
    return o;
}

/* python3 with no shell, no inherited environment and its own process group */
static char *code_executor_run(const char *code, int timeout_s, int *exit_code, char **err_out)
{
    char scratch[] = "/tmp/edge-code-XXXXXX";
    if (!mkdtemp(scratch)) {
        *err_out = strdup("scratch_failed");
        *exit_code = -1;
        return NULL;
    }
    int outp[2];
    if (pipe(outp) != 0) {
        *err_out = strdup("pipe_failed");
        *exit_code = -1;
        edge_rm_rf(scratch);
        return NULL;
    }
    char home[64];
    snprintf(home, sizeof(home), "HOME=%s", scratch);
    char *envp[] = { "PATH=/usr/local/bin:/usr/bin:/bin", home, NULL };
    char *argv[] = { "python3", "-I", "-c", (char *)code, NULL };

    pid_t pid = fork();
    if (pid < 0) {
        close(outp[0]); close(outp[1]);
        *err_out = strdup("fork_failed");
        *exit_code = -1;
        edge_rm_rf(scratch);
        return NULL;
    }
    if (pid == 0) {
        setsid();
        int devnull = open("/dev/null", O_RDONLY);
        if (devnull >= 0) dup2(devnull, 0);
        dup2(outp[1], 1);
        dup2(outp[1], 2);
        /* a pod holds client sockets and the broker link, none of them go to the child */
        for (int fd = 3; fd < 1024; fd++) close(fd);
        if (chdir(scratch) != 0) _exit(127);
        struct rlimit cpu = { (rlim_t)timeout_s + 1, (rlim_t)timeout_s + 1 };
        struct rlimit fsize = { 16u * 1024 * 1024, 16u * 1024 * 1024 };
        setrlimit(RLIMIT_CPU, &cpu);
        setrlimit(RLIMIT_FSIZE, &fsize);
        execvpe("python3", argv, envp);
        _exit(127);
    }
    close(outp[1]);

    sbuf_t out = {0};
    char buf[4096];
    long deadline = now_ms() + timeout_s * 1000L;
    int timed_out = 0;
    for (;;) {
        long left = deadline - now_ms();
        if (left <= 0) { timed_out = 1; break; }
        struct pollfd pfd = { outp[0], POLLIN, 0 };
        int pr = poll(&pfd, 1, (int)left);
        if (pr < 0 && errno == EINTR) continue;
        if (pr <= 0) { timed_out = pr == 0; break; }
        ssize_t n = read(outp[0], buf, sizeof(buf));
        if (n <= 0) break;
        if (out.len < EDGE_CODE_OUTPUT_BYTES) {
            size_t room = EDGE_CODE_OUTPUT_BYTES - out.len;
            sbuf_add(&out, buf, (size_t)n < room ? (size_t)n : room);
        }
    }
    close(outp[0]);
    /* the whole group, a forked child must not outlive the limit */
    if (timed_out) kill(-pid, SIGKILL);
    int wstatus = 0;
    if (!timed_out) {
        /* stdout closed, give the child a moment to exit on its own */
        for (int i = 0; i < 50; i++) {
            if (waitpid(pid, &wstatus, WNOHANG) == pid) { pid = 0; break; }
            usleep(100000);
        }
        if (pid) {
            kill(-pid, SIGKILL);
            timed_out = 1;
        }
    }
    if (pid) waitpid(pid, &wstatus, 0);
    edge_rm_rf(scratch);
    if (timed_out) {
        *err_out = strdup("code_executor_timeout");
        *exit_code = -2;
    } else {
        *exit_code = WIFEXITED(wstatus) ? WEXITSTATUS(wstatus) : -1;
    }
    return out.buf ? out.buf : strdup("");
}

static char *request_json(const edge_agent_t *agent, const char *user_message)
{
    struct json_object *root = json_object_new_object();
    json_object_object_add(root, "model", json_object_new_string(agent->model));
    json_object_object_add(root, "max_tokens", json_object_new_int(agent->max_tokens));
    json_object_object_add(root, "temperature", json_object_new_double(agent->temperature));
    json_object_object_add(root, "system", json_object_new_string(agent->system_prompt));
    struct json_object *msgs = json_object_new_array();
    struct json_object *msg = json_object_new_object();
    json_object_object_add(msg, "role", json_object_new_string("user"));
    json_object_object_add(msg, "content", json_object_new_string(user_message));
    json_object_array_add(msgs, msg);
    json_object_object_add(root, "messages", msgs);
    char *out = strdup(json_object_to_json_string_ext(root, JSON_C_TO_STRING_PLAIN));
    json_object_put(root);
    return out;
}

static char *anthropic_call(const edge_config_t *cfg, const edge_agent_t *agent,
                            const char *user_message, int timeout_s,
                            int *http_status, CURLcode *curl_rc)
{
    char base[300];
    snprintf(base, sizeof(base), "%s", cfg->anthropic_base_url);
    size_t n = strlen(base);
    while (n > 0 && base[n - 1] == '/') base[--n] = '\0';
    char url[512];
    snprintf(url, sizeof(url), "%s/v1/messages", base);

    char *body = request_json(agent, user_message);
    CURL *c = curl_easy_init();
    if (!c) { free(body); *http_status = -1; *curl_rc = CURLE_FAILED_INIT; return NULL; }
    sbuf_t resp = {0};
    char auth[1200];
    struct curl_slist *hdrs = NULL;
    if (cfg->anthropic_api_key[0]) {
        snprintf(auth, sizeof(auth), "x-api-key: %s", cfg->anthropic_api_key);
        hdrs = curl_slist_append(hdrs, auth);
    } else {
        snprintf(auth, sizeof(auth), "Authorization: Bearer %s", cfg->anthropic_auth_token);
        hdrs = curl_slist_append(hdrs, auth);
        hdrs = curl_slist_append(hdrs, "anthropic-beta: oauth-2025-04-20");
    }
    hdrs = curl_slist_append(hdrs, "anthropic-version: 2023-06-01");
    hdrs = curl_slist_append(hdrs, "content-type: application/json");
    curl_easy_setopt(c, CURLOPT_URL, url);
    curl_easy_setopt(c, CURLOPT_POSTFIELDS, body);
    curl_easy_setopt(c, CURLOPT_POSTFIELDSIZE, (long)strlen(body));
    curl_easy_setopt(c, CURLOPT_HTTPHEADER, hdrs);
    curl_easy_setopt(c, CURLOPT_WRITEFUNCTION, curl_collect);
    curl_easy_setopt(c, CURLOPT_WRITEDATA, &resp);
    curl_easy_setopt(c, CURLOPT_TIMEOUT, (long)timeout_s);
    curl_easy_setopt(c, CURLOPT_NOSIGNAL, 1L);
    CURLcode rc = curl_easy_perform(c);
    long status = 0;
    curl_easy_getinfo(c, CURLINFO_RESPONSE_CODE, &status);
    curl_slist_free_all(hdrs);
    curl_easy_cleanup(c);
    free(body);
    *http_status = (int)status;
    *curl_rc = rc;
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
    if (!json_object_object_get_ex(root, "content", &content) ||
        !json_object_is_type(content, json_type_array)) {
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
            sbuf_add(&out, t, strlen(t));
        }
    }
    json_object_put(root);
    return out.buf ? out.buf : strdup("");
}

static int has_local_weights(const edge_agent_t *agent)
{
    char weights[EDGE_MAX_PATH * 2];
    snprintf(weights, sizeof(weights), "%s/model_weights", agent->dir);
    struct stat st;
    if (stat(weights, &st) != 0 || !S_ISDIR(st.st_mode)) return 0;
    int found = 0;
    DIR *d = opendir(weights);
    if (d) {
        struct dirent *de;
        while ((de = readdir(d)) != NULL) {
            if (de->d_name[0] != '.') { found = 1; break; }
        }
        closedir(d);
    }
    return found;
}

static char *run_code_path(const edge_config_t *cfg, const edge_agent_t *agent,
                           const char *code, int max_runtime)
{
    if (!cfg->code_enabled) {
        return strdup("{\"ok\":false,\"error\":\"code_executor is off on this gateway, set EDGE_ENABLE_CODE_EXECUTOR=true to allow it\"}");
    }
    int allowed = 0;
    for (int i = 0; i < agent->tool_count; i++) {
        if (strcmp(agent->tools[i], "code_executor") == 0) { allowed = 1; break; }
    }
    if (!allowed) {
        return strdup("{\"ok\":false,\"error\":\"code_executor not in tool whitelist\"}");
    }
    int limit = max_runtime < EDGE_CODE_TIMEOUT_SECS ? max_runtime : EDGE_CODE_TIMEOUT_SECS;
    int rc = 0;
    char *err = NULL;
    char *out = code_executor_run(code, limit, &rc, &err);
    char *esc_out = edge_json_escape(out ? out : "");
    char *esc_err = err ? edge_json_escape(err) : NULL;
    char *result = NULL;
    asprintf(&result, "{\"ok\":%s,\"exit_code\":%d,\"stdout\":\"%s\"%s%s%s}",
             rc == 0 ? "true" : "false", rc, esc_out,
             esc_err ? ",\"error\":\"" : "", esc_err ? esc_err : "", esc_err ? "\"" : "");
    free(out); free(err); free(esc_out); free(esc_err);
    return result;
}

static char *run_model_path(const edge_config_t *cfg, const edge_agent_t *agent,
                            const char *user_message, int max_runtime)
{
    char *result = NULL;
    if (!cfg->anthropic_api_key[0] && !cfg->anthropic_auth_token[0]) {
        char *esc = edge_json_escape(user_message);
        asprintf(&result,
                 "{\"ok\":false,\"error\":\"ANTHROPIC_API_KEY not configured on edge runtime\",\"stub\":true,\"echo\":\"%s\"}",
                 esc);
        free(esc);
        return result;
    }
    int status = 0;
    CURLcode rc = CURLE_OK;
    char *raw = anthropic_call(cfg, agent, user_message, max_runtime, &status, &rc);
    if (rc == CURLE_OPERATION_TIMEDOUT) {
        asprintf(&result,
                 "{\"ok\":false,\"error\":\"max_runtime_seconds exceeded after %d s\",\"error_code\":\"max_runtime_exceeded\"}",
                 max_runtime);
    } else if (rc != CURLE_OK) {
        char *esc = edge_json_escape(curl_easy_strerror(rc));
        asprintf(&result, "{\"ok\":false,\"error\":\"model call failed %s\"}", esc);
        free(esc);
    } else if (status >= 200 && status < 300) {
        char *txt = extract_text(raw ? raw : "");
        char *esc = edge_json_escape(txt);
        asprintf(&result, "{\"ok\":true,\"text\":\"%s\"}", esc);
        free(txt); free(esc);
    } else {
        char shown[301];
        snprintf(shown, sizeof(shown), "%s", raw ? raw : "no response");
        char *esc = edge_json_escape(shown);
        asprintf(&result, "{\"ok\":false,\"error\":\"model call answered %d %s\"}", status, esc);
        free(esc);
    }
    free(raw);
    return result;
}

char *agent_execute_json(const edge_config_t *cfg, const edge_agent_t *agent,
                         const char *body, size_t body_len, int *http_status)
{
    *http_status = 200;
    char *user_message = strdup("");
    char *code = NULL;
    if (body_len > 0 && body) {
        struct json_object *root = json_tokener_parse(body);
        if (!root || !json_object_is_type(root, json_type_object)) {
            if (root) json_object_put(root);
            free(user_message);
            *http_status = 400;
            return strdup("{\"error\":\"body is not valid JSON\"}");
        }
        struct json_object *m = NULL;
        if (json_object_object_get_ex(root, "message", &m) &&
            json_object_is_type(m, json_type_string)) {
            free(user_message);
            user_message = strdup(json_object_get_string(m));
        }
        struct json_object *params = NULL, *cv = NULL;
        if (json_object_object_get_ex(root, "params", &params) &&
            json_object_is_type(params, json_type_object) &&
            json_object_object_get_ex(params, "code", &cv) &&
            json_object_is_type(cv, json_type_string)) {
            code = strdup(json_object_get_string(cv));
        }
        json_object_put(root);
    }

    if ((int)strlen(user_message) > agent->max_payload_bytes) {
        char *err = NULL;
        asprintf(&err, "{\"ok\":false,\"error\":\"payload exceeds %d bytes\"}",
                 agent->max_payload_bytes);
        free(user_message); free(code);
        return err;
    }

    int max_runtime = agent->max_runtime_seconds > 0 ? agent->max_runtime_seconds : 30;
    long started = now_ms();
    char *result_json = NULL;
    if (has_local_weights(agent)) {
        result_json = strdup("{\"ok\":false,\"error\":\"local model_weights present but no local inference shipped in v1.1\",\"phase_2\":true}");
    } else if (code && *code) {
        result_json = run_code_path(cfg, agent, code, max_runtime);
    } else {
        result_json = run_model_path(cfg, agent, user_message, max_runtime);
    }

    long duration = now_ms() - started;
    char *full = NULL;
    asprintf(&full, "{\"slug\":\"%s\",\"digest\":\"%s\",\"duration_ms\":%ld,\"result\":%s}",
             agent->slug, agent->digest_hex, duration, result_json);
    free(result_json);
    free(user_message);
    free(code);
    return full;
}
