#include <microhttpd.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#include "runtime.h"

#if MHD_VERSION >= 0x00097002
typedef enum MHD_Result mhd_rc_t;
#else
typedef int mhd_rc_t;
#endif

typedef struct {
    char  *body;
    size_t len;
    size_t cap;
} request_state_t;

static mhd_rc_t send_json(struct MHD_Connection *c, int status, const char *body)
{
    size_t n = strlen(body);
    char *copy = (char *)malloc(n);
    memcpy(copy, body, n);
    struct MHD_Response *resp = MHD_create_response_from_buffer(
        n, copy, MHD_RESPMEM_MUST_FREE);
    MHD_add_response_header(resp, "Content-Type", "application/json");
    mhd_rc_t rc = MHD_queue_response(c, (unsigned)status, resp);
    MHD_destroy_response(resp);
    return rc;
}

static mhd_rc_t handle(void *cls, struct MHD_Connection *conn,
                       const char *url, const char *method,
                       const char *version, const char *upload_data,
                       size_t *upload_data_size, void **con_cls)
{
    (void)version;
    edge_ctx_t *ctx = (edge_ctx_t *)cls;

    if (*con_cls == NULL) {
        request_state_t *st = (request_state_t *)calloc(1, sizeof(*st));
        *con_cls = st;
        return MHD_YES;
    }
    request_state_t *st = (request_state_t *)*con_cls;

    if (*upload_data_size > 0) {
        if (st->len + *upload_data_size + 1 > st->cap) {
            while (st->len + *upload_data_size + 1 > st->cap) {
                st->cap = st->cap ? st->cap * 2 : 4096;
            }
            st->body = (char *)realloc(st->body, st->cap);
        }
        memcpy(st->body + st->len, upload_data, *upload_data_size);
        st->len += *upload_data_size;
        st->body[st->len] = '\0';
        *upload_data_size = 0;
        return MHD_YES;
    }

    /* GET /health */
    if (strcmp(method, "GET") == 0 && strcmp(url, "/health") == 0) {
        char buf[256];
        snprintf(buf, sizeof(buf),
                 "{\"status\":\"ok\",\"agents\":%d,\"gateway_id\":\"%s\"}",
                 registry_count(ctx->registry), ctx->cfg->gateway_id);
        return send_json(conn, 200, buf);
    }

    /* GET /agents */
    if (strcmp(method, "GET") == 0 && strcmp(url, "/agents") == 0) {
        char *list = registry_list_json(ctx->registry);
        mhd_rc_t rc = send_json(conn, 200, list);
        free(list);
        return rc;
    }

    /* POST /agents/{slug}/execute */
    const char *prefix = "/agents/";
    const char *suffix_exec = "/execute";
    const char *suffix_bundle = "/bundle";
    if (strcmp(method, "POST") == 0 &&
        strncmp(url, prefix, strlen(prefix)) == 0) {
        size_t ulen = strlen(url);
        size_t plen = strlen(prefix);
        if (ulen > plen + strlen(suffix_exec) &&
            strcmp(url + ulen - strlen(suffix_exec), suffix_exec) == 0) {
            char slug[EDGE_MAX_SLUG];
            size_t sl = ulen - plen - strlen(suffix_exec);
            if (sl >= sizeof(slug)) sl = sizeof(slug) - 1;
            memcpy(slug, url + plen, sl);
            slug[sl] = '\0';
            edge_agent_t *agent = registry_get(ctx->registry, slug);
            if (!agent) {
                char buf[256];
                snprintf(buf, sizeof(buf),
                         "{\"error\":\"unknown agent %s\"}", slug);
                return send_json(conn, 404, buf);
            }
            char *result = agent_execute_json(ctx->cfg, agent,
                                              st->body ? st->body : "",
                                              st->len);
            mhd_rc_t rc = send_json(conn, 200, result);
            free(result);
            return rc;
        }
        /* POST /agents/{slug}/bundle — write body to tmp, install. */
        if (ulen > plen + strlen(suffix_bundle) &&
            strcmp(url + ulen - strlen(suffix_bundle), suffix_bundle) == 0) {
            char tmp[] = "/tmp/edge-http-bundle-XXXXXX";
            int fd = mkstemp(tmp);
            if (fd < 0) {
                return send_json(conn, 500, "{\"error\":\"tmp_failed\"}");
            }
            if (st->body && st->len > 0) {
                if (write(fd, st->body, st->len) != (ssize_t)st->len) {
                    close(fd); unlink(tmp);
                    return send_json(conn, 500, "{\"error\":\"write_failed\"}");
                }
            }
            close(fd);
            edge_agent_t loaded;
            int rc = bundle_install_from_file(ctx->registry, ctx->cfg, tmp, &loaded);
            unlink(tmp);
            if (rc != 0) {
                return send_json(conn, 400, "{\"error\":\"bundle_install_failed\"}");
            }
            char *list = registry_list_json(ctx->registry);
            (void)list;
            char buf[1024];
            snprintf(buf, sizeof(buf),
                     "{\"loaded\":{\"slug\":\"%s\",\"digest\":\"%s\"}}",
                     loaded.slug, loaded.digest_hex);
            free(list);
            return send_json(conn, 200, buf);
        }
    }

    return send_json(conn, 404, "{\"error\":\"not found\"}");
}

static void cleanup(void *cls, struct MHD_Connection *c, void **con_cls,
                    enum MHD_RequestTerminationCode toe)
{
    (void)cls; (void)c; (void)toe;
    if (*con_cls) {
        request_state_t *st = (request_state_t *)*con_cls;
        free(st->body);
        free(st);
        *con_cls = NULL;
    }
}

void *http_thread(void *arg)
{
    edge_ctx_t *ctx = (edge_ctx_t *)arg;
    struct MHD_Daemon *d = MHD_start_daemon(
        MHD_USE_INTERNAL_POLLING_THREAD | MHD_USE_ERROR_LOG,
        (uint16_t)ctx->cfg->port,
        NULL, NULL,
        &handle, ctx,
        MHD_OPTION_NOTIFY_COMPLETED, cleanup, NULL,
        MHD_OPTION_CONNECTION_LIMIT, 64,
        MHD_OPTION_END);
    if (!d) {
        edge_log("ERROR", "http_start_failed port=%d", ctx->cfg->port);
        return NULL;
    }
    edge_log("INFO", "http_listening port=%d", ctx->cfg->port);
    for (;;) sleep(3600);
    return NULL;
}
