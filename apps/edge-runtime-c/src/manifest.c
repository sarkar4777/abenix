#include <ctype.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "runtime.h"

static const char *EDGE_SAFE_TOOLS[] = {
    "mqtt_publish", "mqtt_subscribe", "current_time",
    "windowed_state", "connector_call", "code_executor",
    NULL,
};

static int is_edge_safe(const char *tool)
{
    for (int i = 0; EDGE_SAFE_TOOLS[i]; i++) {
        if (strcmp(tool, EDGE_SAFE_TOOLS[i]) == 0) return 1;
    }
    return 0;
}

static void trim(char *s)
{
    size_t n = strlen(s);
    while (n > 0 && (s[n - 1] == '\r' || s[n - 1] == '\n' ||
                     s[n - 1] == ' '  || s[n - 1] == '\t')) {
        s[--n] = '\0';
    }
    size_t i = 0;
    while (s[i] == ' ' || s[i] == '\t') i++;
    if (i > 0) memmove(s, s + i, strlen(s + i) + 1);
}

static int leading_spaces(const char *s)
{
    int n = 0;
    while (s[n] == ' ') n++;
    return n;
}

static void unquote(char *s)
{
    size_t n = strlen(s);
    if (n >= 2 && ((s[0] == '"' && s[n - 1] == '"') ||
                   (s[0] == '\'' && s[n - 1] == '\''))) {
        memmove(s, s + 1, n - 2);
        s[n - 2] = '\0';
    }
}

static void copy_str(char *dst, size_t cap, const char *src)
{
    strncpy(dst, src, cap - 1);
    dst[cap - 1] = '\0';
}

static int add_tool(edge_agent_t *agent, const char *name)
{
    if (agent->tool_count >= EDGE_MAX_TOOLS || strlen(name) >= EDGE_MAX_TOOL_NAME) {
        edge_log("ERROR", "manifest_tool_list_too_long");
        return -1;
    }
    copy_str(agent->tools[agent->tool_count], EDGE_MAX_TOOL_NAME, name);
    agent->tool_count++;
    return 0;
}

/* narrow yaml subset, top level scalars, the tools list and the two edge limits */
int manifest_parse_yaml(const char *yaml_text, size_t len, edge_agent_t *agent)
{
    char *buf = (char *)malloc(len + 1);
    if (!buf) return -1;
    memcpy(buf, yaml_text, len);
    buf[len] = '\0';

    agent->max_payload_bytes = 65536;
    agent->max_runtime_seconds = 30;
    agent->temperature = 0.7;
    agent->max_iterations = 10;
    agent->max_tokens = 1024;
    agent->tool_count = 0;

    enum { TOP, IN_TOOLS, IN_EDGE } state = TOP;
    int edge_indent = -1;

    char *line, *save;
    for (line = strtok_r(buf, "\n", &save); line; line = strtok_r(NULL, "\n", &save)) {
        if (!*line || line[0] == '#') continue;
        int indent = leading_spaces(line);
        char copy[1024];
        copy_str(copy, sizeof(copy), line);
        char *raw = copy;
        while (*raw == ' ') raw++;
        if (!*raw) continue;

        /* tools list item, PyYAML writes these at the key's own indent */
        if (state == IN_TOOLS && raw[0] == '-') {
            char *v = raw + 1;
            while (*v == ' ') v++;
            trim(v);
            unquote(v);
            if (*v && add_tool(agent, v) != 0) {
                free(buf);
                return -1;
            }
            continue;
        }

        if (state == IN_TOOLS && indent == 0) state = TOP;
        if (state == IN_EDGE && indent <= edge_indent) state = TOP;
        /* an indented line here continues a scalar such as a long description, never a real key */
        if (state == TOP && indent > 0) continue;

        char *colon = strchr(raw, ':');
        if (!colon) continue;
        *colon = '\0';
        char *key = raw;
        char *val = colon + 1;
        while (*val == ' ') val++;
        trim(val);
        unquote(val);

        if (state == IN_EDGE) {
            if (strcmp(key, "max_payload_bytes") == 0) {
                agent->max_payload_bytes = atoi(val);
            } else if (strcmp(key, "max_runtime_seconds") == 0) {
                agent->max_runtime_seconds = atoi(val);
            }
            continue;
        }

        if (strcmp(key, "name") == 0) {
            copy_str(agent->name, sizeof(agent->name), val);
        } else if (strcmp(key, "slug") == 0) {
            /* too long fails the slug check, never a silently shortened name */
            if (strlen(val) >= sizeof(agent->slug)) val[0] = '.';
            copy_str(agent->slug, sizeof(agent->slug), val);
        } else if (strcmp(key, "tenant_id") == 0) {
            copy_str(agent->tenant_id, sizeof(agent->tenant_id), val);
        } else if (strcmp(key, "version") == 0) {
            copy_str(agent->version, sizeof(agent->version), val);
        } else if (strcmp(key, "model") == 0) {
            copy_str(agent->model, sizeof(agent->model), val);
        } else if (strcmp(key, "temperature") == 0) {
            agent->temperature = atof(val);
        } else if (strcmp(key, "max_iterations") == 0) {
            agent->max_iterations = atoi(val);
        } else if (strcmp(key, "max_tokens") == 0) {
            agent->max_tokens = atoi(val);
        } else if (strcmp(key, "tools") == 0) {
            /* either inline [a, b] or empty meaning block list follows. */
            if (val[0] == '[') {
                char *p = val + 1;
                char *end = strchr(p, ']');
                if (end) *end = '\0';
                char *tok, *ts;
                for (tok = strtok_r(p, ",", &ts); tok; tok = strtok_r(NULL, ",", &ts)) {
                    trim(tok);
                    unquote(tok);
                    if (*tok && add_tool(agent, tok) != 0) {
                        free(buf);
                        return -1;
                    }
                }
            } else {
                state = IN_TOOLS;
            }
        } else if (strcmp(key, "edge_constraints") == 0) {
            state = IN_EDGE;
            edge_indent = indent;
        }
    }

    free(buf);
    if (!agent->slug[0] || !agent->name[0] || !agent->version[0] ||
        !agent->model[0]) {
        return -1;
    }
    return 0;
}

int manifest_validate(const edge_agent_t *agent, char *err, size_t err_cap)
{
    if (!agent->slug[0] || !agent->name[0] || !agent->version[0] ||
        !agent->model[0]) {
        snprintf(err, err_cap, "manifest missing required fields");
        return -1;
    }
    if (!edge_valid_slug(agent->slug)) {
        snprintf(err, err_cap, "manifest slug is not a safe name");
        return -1;
    }
    for (int i = 0; i < agent->tool_count; i++) {
        if (!is_edge_safe(agent->tools[i])) {
            snprintf(err, err_cap, "tool not edge-safe %s", agent->tools[i]);
            return -1;
        }
    }
    return 0;
}
