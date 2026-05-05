#include <errno.h>
#include <mosquitto.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#include "runtime.h"

static void parse_mqtt_url(const char *url, char *host, size_t host_cap, int *port)
{
    *port = 1883;
    host[0] = '\0';
    const char *s = url;
    if (strncmp(s, "mqtt://", 7) == 0) s += 7;
    if (strncmp(s, "tcp://",  6) == 0) s += 6;
    const char *colon = strchr(s, ':');
    const char *slash = strchr(s, '/');
    const char *end = slash ? slash : s + strlen(s);
    if (colon && colon < end) {
        size_t hl = (size_t)(colon - s);
        if (hl >= host_cap) hl = host_cap - 1;
        memcpy(host, s, hl);
        host[hl] = '\0';
        *port = atoi(colon + 1);
        if (*port <= 0) *port = 1883;
    } else {
        size_t hl = (size_t)(end - s);
        if (hl >= host_cap) hl = host_cap - 1;
        memcpy(host, s, hl);
        host[hl] = '\0';
    }
    if (!host[0]) snprintf(host, host_cap, "localhost");
}

static void on_connect(struct mosquitto *m, void *ud, int rc)
{
    edge_ctx_t *ctx = (edge_ctx_t *)ud;
    char topic[256];
    snprintf(topic, sizeof(topic), "edge.%s.deploy", ctx->cfg->gateway_id);
    edge_log("INFO", "mqtt_connected rc=%d topic=%s", rc, topic);
    mosquitto_subscribe(m, NULL, topic, 1);
}

static void on_message(struct mosquitto *m, void *ud, const struct mosquitto_message *msg)
{
    (void)m;
    edge_ctx_t *ctx = (edge_ctx_t *)ud;
    if (!msg || !msg->payload || msg->payloadlen <= 0) return;

    char tmp_path[] = "/tmp/edge-bundle-XXXXXX";
    int fd = mkstemp(tmp_path);
    if (fd < 0) {
        edge_log("ERROR", "mqtt_tmpfile_failed err=%s", strerror(errno));
        return;
    }
    ssize_t w = write(fd, msg->payload, (size_t)msg->payloadlen);
    close(fd);
    if (w != msg->payloadlen) {
        edge_log("ERROR", "mqtt_tmp_write_short");
        unlink(tmp_path);
        return;
    }
    edge_agent_t loaded;
    int rc = bundle_install_from_file(ctx->registry, ctx->cfg, tmp_path, &loaded);
    if (rc == 0) {
        edge_log("INFO", "mqtt_bundle_loaded slug=%s", loaded.slug);
    } else {
        edge_log("ERROR", "mqtt_bundle_failed rc=%d", rc);
    }
    unlink(tmp_path);
}

void *mqtt_thread(void *arg)
{
    edge_ctx_t *ctx = (edge_ctx_t *)arg;
    if (!ctx->cfg->mqtt_url[0]) {
        edge_log("INFO", "mqtt_disabled");
        return NULL;
    }
    char host[256];
    int port = 1883;
    parse_mqtt_url(ctx->cfg->mqtt_url, host, sizeof(host), &port);

    mosquitto_lib_init();
    char client_id[160];
    snprintf(client_id, sizeof(client_id), "edge-c-%s", ctx->cfg->gateway_id);
    struct mosquitto *m = mosquitto_new(client_id, true, ctx);
    if (!m) {
        edge_log("ERROR", "mqtt_new_failed");
        return NULL;
    }
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
