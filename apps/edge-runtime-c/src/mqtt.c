#include <errno.h>
#include <mosquitto.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#include "runtime.h"

/* mqtt://user:pass@host:port, anything missing falls back to no login and 1883 */
static void parse_mqtt_url(const char *url, char *host, size_t host_cap, int *port,
                           char *user, size_t user_cap, char *pass, size_t pass_cap)
{
    *port = 1883;
    host[0] = user[0] = pass[0] = '\0';
    const char *s = strstr(url, "://");
    s = s ? s + 3 : url;
    const char *slash = strchr(s, '/');
    const char *end = slash ? slash : s + strlen(s);
    const char *at = NULL;
    for (const char *p = s; p < end; p++) {
        if (*p == '@') at = p;
    }
    if (at) {
        const char *sep = memchr(s, ':', (size_t)(at - s));
        const char *uend = sep ? sep : at;
        snprintf(user, user_cap, "%.*s", (int)(uend - s), s);
        if (sep) snprintf(pass, pass_cap, "%.*s", (int)(at - sep - 1), sep + 1);
        s = at + 1;
    }
    const char *colon = memchr(s, ':', (size_t)(end - s));
    if (colon) {
        snprintf(host, host_cap, "%.*s", (int)(colon - s), s);
        *port = atoi(colon + 1);
        if (*port <= 0) *port = 1883;
    } else {
        snprintf(host, host_cap, "%.*s", (int)(end - s), s);
    }
    if (!host[0]) snprintf(host, host_cap, "localhost");
}

static void on_connect(struct mosquitto *m, void *ud, int rc)
{
    edge_ctx_t *ctx = (edge_ctx_t *)ud;
    char topic[256];
    snprintf(topic, sizeof(topic), "edge/%s/deploy/+", ctx->cfg->gateway_id);
    edge_log("INFO", "mqtt_connected rc=%d topic=%s", rc, topic);
    mosquitto_subscribe(m, NULL, topic, 1);
}

static void on_message(struct mosquitto *m, void *ud, const struct mosquitto_message *msg)
{
    edge_ctx_t *ctx = (edge_ctx_t *)ud;
    /* clearing a retained bundle arrives as an empty message */
    if (!msg || !msg->payload || msg->payloadlen <= 0) return;
    char prefix[256];
    snprintf(prefix, sizeof(prefix), "edge/%s/deploy/", ctx->cfg->gateway_id);
    size_t plen = strlen(prefix);
    if (strncmp(msg->topic, prefix, plen) != 0) return;
    const char *slug = msg->topic + plen;

    char digest[65];
    bundle_digest_hex((const unsigned char *)msg->payload, (size_t)msg->payloadlen, digest);
    edge_agent_t *loaded = (edge_agent_t *)malloc(sizeof(*loaded));
    char err[512] = "";
    int rc = loaded ? bundle_install_bytes(ctx->registry, ctx->cfg,
                                           (const unsigned char *)msg->payload,
                                           (size_t)msg->payloadlen, slug, loaded, err, sizeof(err))
                    : -1;
    free(loaded);

    char *esc_slug = edge_json_escape(slug);
    char *esc_err = edge_json_escape(err);
    char ack[1400];
    if (rc == 0) {
        edge_log("INFO", "mqtt_bundle_loaded slug=%s", slug);
        snprintf(ack, sizeof(ack), "{\"slug\":\"%s\",\"digest\":\"%s\",\"ok\":true}", esc_slug, digest);
    } else {
        edge_log("ERROR", "mqtt_bundle_failed slug=%s err=%s", slug, err);
        snprintf(ack, sizeof(ack), "{\"slug\":\"%s\",\"digest\":\"%s\",\"ok\":false,\"error\":\"%s\"}", esc_slug, digest, esc_err);
    }
    free(esc_slug);
    free(esc_err);
    char topic[400];
    snprintf(topic, sizeof(topic), "edge/%s/ack/%s", ctx->cfg->gateway_id, slug);
    mosquitto_publish(m, NULL, topic, (int)strlen(ack), ack, 1, false);
}

void *mqtt_thread(void *arg)
{
    edge_ctx_t *ctx = (edge_ctx_t *)arg;
    if (!ctx->cfg->mqtt_url[0]) {
        edge_log("INFO", "mqtt_disabled");
        return NULL;
    }
    char host[256], user[128], pass[256];
    int port = 1883;
    parse_mqtt_url(ctx->cfg->mqtt_url, host, sizeof(host), &port, user, sizeof(user), pass, sizeof(pass));

    mosquitto_lib_init();
    char client_id[160];
    snprintf(client_id, sizeof(client_id), "edge-c-%s", ctx->cfg->gateway_id);
    struct mosquitto *m = mosquitto_new(client_id, true, ctx);
    if (!m) {
        edge_log("ERROR", "mqtt_new_failed");
        return NULL;
    }
    if (user[0]) mosquitto_username_pw_set(m, user, pass);
    mosquitto_connect_callback_set(m, on_connect);
    mosquitto_message_callback_set(m, on_message);

    for (;;) {
        int rc = mosquitto_connect(m, host, port, 60);
        if (rc != MOSQ_ERR_SUCCESS) {
            edge_log("WARN", "mqtt_connect_failed host=%s port=%d rc=%d", host, port, rc);
            sleep(10);
            continue;
        }
        mosquitto_loop_forever(m, -1, 1);
        sleep(5);
    }
    return NULL;
}
