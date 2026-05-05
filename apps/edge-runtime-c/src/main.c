#include <errno.h>
#include <pthread.h>
#include <signal.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <time.h>
#include <unistd.h>

#include "runtime.h"

static volatile sig_atomic_t g_stopping = 0;

void edge_log(const char *level, const char *fmt, ...)
{
    char ts[32];
    time_t now = time(NULL);
    struct tm tm;
#if defined(_WIN32)
    gmtime_s(&tm, &now);
#else
    gmtime_r(&now, &tm);
#endif
    strftime(ts, sizeof(ts), "%Y-%m-%dT%H:%M:%SZ", &tm);
    fprintf(stderr, "%s %s edge-runtime ", ts, level);
    va_list ap;
    va_start(ap, fmt);
    vfprintf(stderr, fmt, ap);
    va_end(ap);
    fputc('\n', stderr);
    fflush(stderr);
}

static void on_signal(int sig)
{
    (void)sig;
    g_stopping = 1;
    edge_log("INFO", "shutting down");
    _exit(0);
}

static void getenv_into(const char *key, char *dst, size_t cap, const char *fallback)
{
    const char *v = getenv(key);
    if (v && *v) {
        strncpy(dst, v, cap - 1);
        dst[cap - 1] = '\0';
    } else if (fallback) {
        strncpy(dst, fallback, cap - 1);
        dst[cap - 1] = '\0';
    } else {
        dst[0] = '\0';
    }
}

static void mkdir_p(const char *path)
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

static void load_config(edge_config_t *cfg, int argc, char **argv)
{
    memset(cfg, 0, sizeof(*cfg));
    getenv_into("GATEWAY_ID", cfg->gateway_id, sizeof(cfg->gateway_id), "edge-local");
    getenv_into("GATEWAY_NAME", cfg->gateway_name, sizeof(cfg->gateway_name), cfg->gateway_id);
    getenv_into("PLATFORM_URL", cfg->platform_url, sizeof(cfg->platform_url),
                "http://host.docker.internal:8000");
    getenv_into("PLATFORM_TOKEN", cfg->platform_token, sizeof(cfg->platform_token), "");
    getenv_into("MQTT_URL", cfg->mqtt_url, sizeof(cfg->mqtt_url), "");
    getenv_into("SIGNING_PUBKEY_PATH", cfg->signing_pubkey_path,
                sizeof(cfg->signing_pubkey_path), "/etc/edge/signing_pub.pem");
    getenv_into("BUNDLE_DIR", cfg->bundle_dir, sizeof(cfg->bundle_dir),
                "/var/edge/agents");
    getenv_into("ENDPOINT_URL", cfg->endpoint_url, sizeof(cfg->endpoint_url), "");
    getenv_into("ANTHROPIC_API_KEY", cfg->anthropic_api_key,
                sizeof(cfg->anthropic_api_key), "");
    getenv_into("ANTHROPIC_BASE_URL", cfg->anthropic_base_url,
                sizeof(cfg->anthropic_base_url), "https://api.anthropic.com");

    const char *port_env = getenv("PORT");
    cfg->port = port_env && *port_env ? atoi(port_env) : 8080;

    for (int i = 1; i + 1 < argc; i++) {
        if (strcmp(argv[i], "--port") == 0) {
            cfg->port = atoi(argv[i + 1]);
            i++;
        }
    }

    mkdir_p(cfg->bundle_dir);
}

int main(int argc, char **argv)
{
    edge_config_t cfg;
    edge_registry_t registry;

    signal(SIGTERM, on_signal);
    signal(SIGINT, on_signal);
    signal(SIGPIPE, SIG_IGN);

    load_config(&cfg, argc, argv);
    registry_init(&registry);
    registry_reload_from_disk(&registry, &cfg);

    edge_ctx_t ctx = { .cfg = &cfg, .registry = &registry };

    pthread_t t_register, t_mqtt, t_http;
    pthread_create(&t_register, NULL, register_loop_thread, &ctx);
    pthread_create(&t_mqtt, NULL, mqtt_thread, &ctx);
    pthread_create(&t_http, NULL, http_thread, &ctx);

    edge_log("INFO", "started gateway_id=%s port=%d bundle_dir=%s",
             cfg.gateway_id, cfg.port, cfg.bundle_dir);

    pthread_join(t_http, NULL);
    return 0;
}
