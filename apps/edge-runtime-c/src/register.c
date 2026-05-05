#include <curl/curl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#include "runtime.h"

static size_t discard_cb(void *p, size_t s, size_t n, void *u)
{
    (void)p; (void)u;
    return s * n;
}

static void register_once(const edge_config_t *cfg)
{
    if (!cfg->platform_url[0] || !cfg->platform_token[0]) {
        edge_log("WARN", "skip_register: PLATFORM_URL=%d PLATFORM_TOKEN=%d",
                 cfg->platform_url[0] != 0, cfg->platform_token[0] != 0);
        return;
    }
    CURL *c = curl_easy_init();
    if (!c) return;

    char base[600];
    strncpy(base, cfg->platform_url, sizeof(base) - 1);
    base[sizeof(base) - 1] = '\0';
    size_t bn = strlen(base);
    while (bn > 0 && base[bn - 1] == '/') base[--bn] = '\0';

    char url[1024];
    snprintf(url, sizeof(url), "%s/api/edge/gateways/register", base);

    char body[1024];
    snprintf(body, sizeof(body),
             "{\"gateway_id\":\"%s\",\"name\":\"%s\",\"endpoint_url\":\"%s\"}",
             cfg->gateway_id, cfg->gateway_name, cfg->endpoint_url);

    char auth[600];
    snprintf(auth, sizeof(auth), "Authorization: Bearer %s", cfg->platform_token);

    struct curl_slist *hdrs = NULL;
    hdrs = curl_slist_append(hdrs, "Content-Type: application/json");
    hdrs = curl_slist_append(hdrs, auth);

    curl_easy_setopt(c, CURLOPT_URL, url);
    curl_easy_setopt(c, CURLOPT_POSTFIELDS, body);
    curl_easy_setopt(c, CURLOPT_POSTFIELDSIZE, (long)strlen(body));
    curl_easy_setopt(c, CURLOPT_HTTPHEADER, hdrs);
    curl_easy_setopt(c, CURLOPT_WRITEFUNCTION, discard_cb);
    curl_easy_setopt(c, CURLOPT_TIMEOUT, 8L);
    curl_easy_setopt(c, CURLOPT_NOSIGNAL, 1L);

    CURLcode rc = curl_easy_perform(c);
    long status = 0;
    curl_easy_getinfo(c, CURLINFO_RESPONSE_CODE, &status);
    if (rc == CURLE_OK && status >= 200 && status < 300) {
        edge_log("INFO", "registered_with_platform status=%ld", status);
    } else {
        edge_log("WARN", "register_failed status=%ld rc=%d err=%s",
                 status, rc, curl_easy_strerror(rc));
    }
    curl_slist_free_all(hdrs);
    curl_easy_cleanup(c);
}

void *register_loop_thread(void *arg)
{
    edge_ctx_t *ctx = (edge_ctx_t *)arg;
    for (;;) {
        register_once(ctx->cfg);
        sleep(60);
    }
    return NULL;
}
