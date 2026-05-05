#include <dirent.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/types.h>

#include "runtime.h"

void registry_init(edge_registry_t *r)
{
    memset(r, 0, sizeof(*r));
    pthread_mutex_init(&r->mu, NULL);
}

edge_agent_t *registry_get(edge_registry_t *r, const char *slug)
{
    edge_agent_t *found = NULL;
    pthread_mutex_lock(&r->mu);
    for (int i = 0; i < r->count; i++) {
        if (strcmp(r->agents[i].slug, slug) == 0) {
            found = &r->agents[i];
            break;
        }
    }
    pthread_mutex_unlock(&r->mu);
    return found;
}

int registry_install(edge_registry_t *r, const edge_agent_t *agent)
{
    pthread_mutex_lock(&r->mu);
    for (int i = 0; i < r->count; i++) {
        if (strcmp(r->agents[i].slug, agent->slug) == 0) {
            r->agents[i] = *agent;
            pthread_mutex_unlock(&r->mu);
            return 0;
        }
    }
    if (r->count >= EDGE_MAX_AGENTS) {
        pthread_mutex_unlock(&r->mu);
        return -1;
    }
    r->agents[r->count++] = *agent;
    pthread_mutex_unlock(&r->mu);
    return 0;
}

int registry_count(edge_registry_t *r)
{
    pthread_mutex_lock(&r->mu);
    int n = r->count;
    pthread_mutex_unlock(&r->mu);
    return n;
}

void registry_reload_from_disk(edge_registry_t *r, const edge_config_t *cfg)
{
    DIR *d = opendir(cfg->bundle_dir);
    if (!d) return;
    struct dirent *de;
    while ((de = readdir(d)) != NULL) {
        if (de->d_name[0] == '.') continue;
        char manifest_path[EDGE_MAX_PATH * 2];
        snprintf(manifest_path, sizeof(manifest_path),
                 "%s/%s/agent.yaml", cfg->bundle_dir, de->d_name);
        FILE *fp = fopen(manifest_path, "rb");
        if (!fp) continue;
        if (fseek(fp, 0, SEEK_END) != 0) { fclose(fp); continue; }
        long sz = ftell(fp);
        if (sz <= 0) { fclose(fp); continue; }
        fseek(fp, 0, SEEK_SET);
        char *yaml = (char *)malloc((size_t)sz);
        if (!yaml) { fclose(fp); continue; }
        size_t rd = fread(yaml, 1, (size_t)sz, fp);
        fclose(fp);
        edge_agent_t agent;
        memset(&agent, 0, sizeof(agent));
        if (manifest_parse_yaml(yaml, rd, &agent) == 0 && agent.slug[0]) {
            snprintf(agent.dir, sizeof(agent.dir), "%s/%s",
                     cfg->bundle_dir, de->d_name);
            char prompt_path[EDGE_MAX_PATH * 2];
            snprintf(prompt_path, sizeof(prompt_path),
                     "%s/system_prompt.md", agent.dir);
            FILE *pp = fopen(prompt_path, "rb");
            if (pp) {
                size_t pr = fread(agent.system_prompt, 1,
                                  sizeof(agent.system_prompt) - 1, pp);
                agent.system_prompt[pr] = '\0';
                fclose(pp);
            }
            /* fake digest for reload (matches Python). */
            snprintf(agent.digest_hex, sizeof(agent.digest_hex),
                     "reload-%s", agent.slug);
            registry_install(r, &agent);
            edge_log("INFO", "agent_reloaded_from_disk slug=%s", agent.slug);
        }
        free(yaml);
    }
    closedir(d);
}

static void append(char **buf, size_t *cap, size_t *len, const char *s)
{
    size_t sl = strlen(s);
    if (*len + sl + 1 > *cap) {
        while (*len + sl + 1 > *cap) *cap *= 2;
        *buf = (char *)realloc(*buf, *cap);
    }
    memcpy(*buf + *len, s, sl);
    *len += sl;
    (*buf)[*len] = '\0';
}

static void append_quoted(char **buf, size_t *cap, size_t *len, const char *s)
{
    append(buf, cap, len, "\"");
    for (const char *p = s; *p; p++) {
        char tmp[8];
        if (*p == '"') append(buf, cap, len, "\\\"");
        else if (*p == '\\') append(buf, cap, len, "\\\\");
        else if (*p == '\n') append(buf, cap, len, "\\n");
        else if (*p == '\r') append(buf, cap, len, "\\r");
        else if (*p == '\t') append(buf, cap, len, "\\t");
        else if ((unsigned char)*p < 0x20) {
            snprintf(tmp, sizeof(tmp), "\\u%04x", (unsigned char)*p);
            append(buf, cap, len, tmp);
        } else {
            char c[2] = { *p, 0 };
            append(buf, cap, len, c);
        }
    }
    append(buf, cap, len, "\"");
}

static void agent_to_json(char **buf, size_t *cap, size_t *len,
                          const edge_agent_t *a)
{
    append(buf, cap, len, "{\"slug\":");
    append_quoted(buf, cap, len, a->slug);
    append(buf, cap, len, ",\"name\":");
    append_quoted(buf, cap, len, a->name);
    append(buf, cap, len, ",\"version\":");
    append_quoted(buf, cap, len, a->version);
    append(buf, cap, len, ",\"model\":");
    append_quoted(buf, cap, len, a->model);
    append(buf, cap, len, ",\"digest\":");
    append_quoted(buf, cap, len, a->digest_hex);
    append(buf, cap, len, ",\"tools\":[");
    for (int i = 0; i < a->tool_count; i++) {
        if (i) append(buf, cap, len, ",");
        append_quoted(buf, cap, len, a->tools[i]);
    }
    append(buf, cap, len, "],\"edge_constraints\":{");
    char tmp[64];
    snprintf(tmp, sizeof(tmp), "\"max_payload_bytes\":%d,", a->max_payload_bytes);
    append(buf, cap, len, tmp);
    snprintf(tmp, sizeof(tmp), "\"max_runtime_seconds\":%d", a->max_runtime_seconds);
    append(buf, cap, len, tmp);
    append(buf, cap, len, "}}");
}

char *registry_list_json(edge_registry_t *r)
{
    size_t cap = 256, len = 0;
    char *out = (char *)malloc(cap);
    out[0] = '\0';
    pthread_mutex_lock(&r->mu);
    append(&out, &cap, &len, "{\"agents\":[");
    for (int i = 0; i < r->count; i++) {
        if (i) append(&out, &cap, &len, ",");
        agent_to_json(&out, &cap, &len, &r->agents[i]);
    }
    append(&out, &cap, &len, "]}");
    pthread_mutex_unlock(&r->mu);
    return out;
}
