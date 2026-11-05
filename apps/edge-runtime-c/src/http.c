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
    int    denied;
    int    too_big;
} request_state_t;

static mhd_rc_t send_json_ex(struct MHD_Connection *c, int status, const char *body, int ask_token)
{
    size_t n = strlen(body);
    char *copy = (char *)malloc(n + 1);
    memcpy(copy, body, n);
    struct MHD_Response *resp = MHD_create_response_from_buffer(n, copy, MHD_RESPMEM_MUST_FREE);
    MHD_add_response_header(resp, "Content-Type", "application/json");
    if (ask_token) MHD_add_response_header(resp, "WWW-Authenticate", "Bearer");
    mhd_rc_t rc = MHD_queue_response(c, (unsigned)status, resp);
    MHD_destroy_response(resp);
    return rc;
}

static mhd_rc_t send_json(struct MHD_Connection *c, int status, const char *body)
{
    return send_json_ex(c, status, body, 0);
}

static int token_matches(const char *given, const char *want)
{
    size_t a = strlen(given), b = strlen(want);
    unsigned char diff = a == b ? 0 : 1;
    for (size_t i = 0; i < a; i++) {
        diff |= (unsigned char)(given[i] ^ want[i % (b ? b : 1)]);
    }
    return diff == 0;
}

static int authorized(const edge_config_t *cfg, struct MHD_Connection *conn)
{
    if (cfg->allow_no_auth) return 1;
    if (!cfg->auth_token[0]) return 0;
    const char *h = MHD_lookup_connection_value(conn, MHD_HEADER_KIND, "Authorization");
    if (!h || strncasecmp(h, "Bearer ", 7) != 0) return 0;
    h += 7;
    while (*h == ' ') h++;
    return token_matches(h, cfg->auth_token);
}

/* /agents/{slug}/{verb}, 1 and the slug when it matches, a slug with a slash does not */
static int route_slug(const char *url, const char *verb, char *slug, size_t cap)
{
    const char *prefix = "/agents/";
    size_t plen = strlen(prefix), vlen = strlen(verb), ulen = strlen(url);
    if (strncmp(url, prefix, plen) != 0 || ulen <= plen + vlen + 1) return 0;
    if (strcmp(url + ulen - vlen, verb) != 0 || url[ulen - vlen - 1] != '/') return 0;
    size_t sl = ulen - plen - vlen - 1;
    if (sl >= cap) {
        snprintf(slug, cap, ".");
        return 1;
    }
    memcpy(slug, url + plen, sl);
    slug[sl] = '\0';
    return 1;
}

static mhd_rc_t handle_bundle(edge_ctx_t *ctx, struct MHD_Connection *conn, const char *slug, request_state_t *st)
{
    if (!edge_valid_slug(slug)) {
        return send_json(conn, 400, "{\"error\":\"unsafe agent slug\"}");
    }
    static const char empty[] = "";
    edge_agent_t loaded;
    char err[512] = "";
    int rc = bundle_install_bytes(ctx->registry, ctx->cfg,
                                  st->body ? (const unsigned char *)st->body : (const unsigned char *)empty,
                                  st->len, slug, &loaded, err, sizeof(err));
    if (rc != 0) {
        char *esc = edge_json_escape(err[0] ? err : "bundle_install_failed");
        char buf[1200];
        snprintf(buf, sizeof(buf), "{\"error\":\"%s\",\"slug\":\"%s\"}", esc, slug);
        free(esc);
        return send_json(conn, 400, buf);
    }
    char buf[1024];
    snprintf(buf, sizeof(buf), "{\"loaded\":{\"slug\":\"%s\",\"digest\":\"%s\"}}", loaded.slug, loaded.digest_hex);
    return send_json(conn, 200, buf);
}

static mhd_rc_t handle_execute(edge_ctx_t *ctx, struct MHD_Connection *conn, const char *slug, request_state_t *st)
{
    /* a thread per connection keeps /health open during a model call, so the struct stays off the small stack */
    edge_agent_t *agent = (edge_agent_t *)malloc(sizeof(*agent));
    if (!agent) return send_json(conn, 500, "{\"error\":\"out of memory\"}");
    if (!edge_valid_slug(slug) || !registry_get(ctx->registry, slug, agent)) {
        free(agent);
        char *esc = edge_json_escape(slug);
        char buf[256];
        snprintf(buf, sizeof(buf), "{\"error\":\"unknown agent %.150s\"}", esc);
        free(esc);
        return send_json(conn, 404, buf);
    }
    int status = 200;
    char *result = agent_execute_json(ctx->cfg, agent, st->body ? st->body : "", st->len, &status);
    free(agent);
    mhd_rc_t rc = send_json(conn, status, result);
    free(result);
    return rc;
}

static mhd_rc_t handle(void *cls, struct MHD_Connection *conn,
                       const char *url, const char *method,
                       const char *version, const char *upload_data,
                       size_t *upload_data_size, void **con_cls)
{
    (void)version;
    edge_ctx_t *ctx = (edge_ctx_t *)cls;
    int is_post = strcmp(method, "POST") == 0;
    char slug[EDGE_MAX_SLUG];
    int is_exec = is_post && route_slug(url, "execute", slug, sizeof(slug));
    int is_bundle = !is_exec && is_post && route_slug(url, "bundle", slug, sizeof(slug));

    if (*con_cls == NULL) {
        request_state_t *st = (request_state_t *)calloc(1, sizeof(*st));
        /* checked first, a refused caller's body is thrown away unread */
        st->denied = (is_exec || is_bundle) && !authorized(ctx->cfg, conn);
        *con_cls = st;
        return MHD_YES;
    }
    request_state_t *st = (request_state_t *)*con_cls;

    if (*upload_data_size > 0) {
        size_t add = *upload_data_size;
        *upload_data_size = 0;
        if (st->denied || st->too_big) return MHD_YES;
        if (st->len + add > EDGE_MAX_BUNDLE_BYTES) {
            st->too_big = 1;
            return MHD_YES;
        }
        if (st->len + add + 1 > st->cap) {
            while (st->len + add + 1 > st->cap) st->cap = st->cap ? st->cap * 2 : 4096;
            st->body = (char *)realloc(st->body, st->cap);
        }
        memcpy(st->body + st->len, upload_data, add);
        st->len += add;
        st->body[st->len] = '\0';
        return MHD_YES;
    }

    if (st->denied) {
        return send_json_ex(conn, 401,
                            "{\"error\":\"unauthorized\",\"message\":\"Send Authorization: Bearer with this gateway's EDGE_AUTH_TOKEN\"}",
                            1);
    }
    if (st->too_big) {
        return send_json(conn, 413, "{\"error\":\"body is over the size limit\"}");
    }
    if (strcmp(method, "GET") == 0 && strcmp(url, "/health") == 0) {
        char *id = edge_json_escape(ctx->cfg->gateway_id);
        char buf[512];
        snprintf(buf, sizeof(buf), "{\"status\":\"ok\",\"agents\":%d,\"gateway_id\":\"%s\"}",
                 registry_count(ctx->registry), id);
        free(id);
        return send_json(conn, 200, buf);
    }
    if (strcmp(method, "GET") == 0 && strcmp(url, "/agents") == 0) {
        char *list = registry_list_json(ctx->registry);
        mhd_rc_t rc = send_json(conn, 200, list);
        free(list);
        return rc;
    }
    if (is_exec) return handle_execute(ctx, conn, slug, st);
    if (is_bundle) return handle_bundle(ctx, conn, slug, st);
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
        MHD_USE_THREAD_PER_CONNECTION | MHD_USE_INTERNAL_POLLING_THREAD | MHD_USE_ERROR_LOG,
        (uint16_t)ctx->cfg->port,
        NULL, NULL,
        &handle, ctx,
        MHD_OPTION_NOTIFY_COMPLETED, cleanup, NULL,
        MHD_OPTION_CONNECTION_LIMIT, 64,
        MHD_OPTION_THREAD_STACK_SIZE, (size_t)(1024 * 1024),
        MHD_OPTION_END);
    if (!d) {
        edge_log("ERROR", "http_start_failed port=%d", ctx->cfg->port);
        exit(1);
    }
    edge_log("INFO", "http_listening port=%d", ctx->cfg->port);
    for (;;) sleep(3600);
    return NULL;
}
