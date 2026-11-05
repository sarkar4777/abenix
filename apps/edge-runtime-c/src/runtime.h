#ifndef EDGE_RUNTIME_H
#define EDGE_RUNTIME_H

#include <pthread.h>
#include <stddef.h>
#include <stdint.h>

#define EDGE_MAX_AGENTS         64
#define EDGE_MAX_TOOLS          16
#define EDGE_MAX_SLUG           96
#define EDGE_MAX_NAME           128
#define EDGE_MAX_VERSION        32
#define EDGE_MAX_MODEL          96
#define EDGE_MAX_TOOL_NAME      48
#define EDGE_MAX_DIGEST_HEX     72
#define EDGE_MAX_PATH           1024
#define EDGE_MAX_TENANT         64
#define EDGE_MAX_BUNDLE_BYTES   (16 * 1024 * 1024)
#define EDGE_MAX_BUNDLE_MEMBERS 256
#define EDGE_CODE_TIMEOUT_SECS  5
#define EDGE_CODE_OUTPUT_BYTES  (64 * 1024)
#define EDGE_SAVED_BUNDLE       "bundle.agent"

typedef struct {
    char gateway_id[128];
    char gateway_name[128];
    char platform_url[512];
    char platform_token[512];
    char mqtt_url[512];
    char signing_pubkey_path[EDGE_MAX_PATH];
    char signing_pubkey_pem[8192];
    char bundle_dir[EDGE_MAX_PATH];
    char endpoint_url[512];
    char anthropic_api_key[256];
    char anthropic_auth_token[1024];
    char anthropic_base_url[256];
    char auth_token[512];
    char tenant_id[EDGE_MAX_TENANT];
    int  allow_unsigned;
    int  allow_no_auth;
    int  code_enabled;
    int  port;
} edge_config_t;

typedef struct {
    char     slug[EDGE_MAX_SLUG];
    char     name[EDGE_MAX_NAME];
    char     version[EDGE_MAX_VERSION];
    char     model[EDGE_MAX_MODEL];
    char     tenant_id[EDGE_MAX_TENANT];
    double   temperature;
    int      max_iterations;
    int      max_tokens;
    int      max_payload_bytes;
    int      max_runtime_seconds;
    int      tool_count;
    char     tools[EDGE_MAX_TOOLS][EDGE_MAX_TOOL_NAME];
    char     dir[EDGE_MAX_PATH];
    char     digest_hex[EDGE_MAX_DIGEST_HEX];
    char     system_prompt[16384];
} edge_agent_t;

typedef struct {
    edge_agent_t agents[EDGE_MAX_AGENTS];
    int          count;
    pthread_mutex_t mu;
} edge_registry_t;

void edge_log(const char *level, const char *fmt, ...);

void registry_init(edge_registry_t *r);
int  registry_get(edge_registry_t *r, const char *slug, edge_agent_t *out);
int  registry_install(edge_registry_t *r, const edge_agent_t *agent);
int  registry_count(edge_registry_t *r);
void registry_reload_from_disk(edge_registry_t *r, const edge_config_t *cfg);
char *registry_list_json(edge_registry_t *r);

int  bundle_install_bytes(edge_registry_t *r, const edge_config_t *cfg,
                          const unsigned char *raw, size_t raw_len,
                          const char *expected_slug, edge_agent_t *out,
                          char *err, size_t err_cap);
int  bundle_install_from_file(edge_registry_t *r, const edge_config_t *cfg,
                              const char *bundle_path, const char *expected_slug,
                              edge_agent_t *out, char *err, size_t err_cap);
int  bundle_pubkey_state(const edge_config_t *cfg);
void bundle_digest_hex(const unsigned char *buf, size_t n, char out[65]);
int  edge_valid_slug(const char *slug);
int  edge_rm_rf(const char *path);

int  manifest_parse_yaml(const char *yaml_text, size_t len, edge_agent_t *agent);
int  manifest_validate(const edge_agent_t *agent, char *err, size_t err_cap);

void *register_loop_thread(void *arg);
void *mqtt_thread(void *arg);
void *http_thread(void *arg);

char *edge_json_escape(const char *s);
char *agent_execute_json(const edge_config_t *cfg, const edge_agent_t *agent,
                         const char *body, size_t body_len, int *http_status);

typedef struct {
    edge_config_t   *cfg;
    edge_registry_t *registry;
} edge_ctx_t;

#endif
