{{- define "neo4j.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "neo4j.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{- define "neo4j.labels" -}}
helm.sh/chart: {{ include "neo4j.name" . }}
app.kubernetes.io/name: {{ include "neo4j.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/component: graph-database
{{- end }}

{{- define "neo4j.selectorLabels" -}}
app.kubernetes.io/name: {{ include "neo4j.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/* A size like 1g, 512m, 2Gi or 512Mi in mebibytes. */}}
{{- define "neo4j.toMi" -}}
{{- $v := . | toString | lower -}}
{{- $n := regexFind "^[0-9.]+" $v | float64 -}}
{{- if regexMatch "^[0-9.]+(g|gi|gb)$" $v -}}
{{- mulf $n 1024 | int -}}
{{- else if regexMatch "^[0-9.]+(m|mi|mb)$" $v -}}
{{- $n | int -}}
{{- else -}}
{{- fail (printf "neo4j: cannot read the size %s, use a form like 512m or 2g" $v) -}}
{{- end -}}
{{- end -}}

{{/* The image tag with the edition suffix Neo4j publishes. */}}
{{- define "neo4j.image" -}}
{{- $tag := .Values.image.tag | toString -}}
{{- if and (eq (.Values.edition | default "community") "enterprise") (not (contains "enterprise" $tag)) -}}
{{- $tag = printf "%s-enterprise" $tag -}}
{{- end -}}
{{- printf "%s:%s" .Values.image.repository $tag -}}
{{- end -}}

{{/* Fail at install time on settings that would only fail at run time. */}}
{{- define "neo4j.validate" -}}
{{- $edition := .Values.edition | default "community" -}}
{{- if not (has $edition (list "community" "enterprise")) -}}
{{- fail "neo4j.edition must be community or enterprise" -}}
{{- end -}}
{{- if and (eq $edition "enterprise") (not .Values.acceptLicenseAgreement) -}}
{{- fail "neo4j.edition enterprise needs a Neo4j license, set neo4j.acceptLicenseAgreement=true once you hold one" -}}
{{- end -}}
{{- if gt (int (.Values.replicaCount | default 1)) 1 -}}
{{- fail "neo4j.replicaCount must be 1. Community has no clustering and this chart does not set up an Enterprise cluster, use Neo4j's own Helm charts for that" -}}
{{- end -}}
{{- $limit := dig "limits" "memory" "" (.Values.resources | default dict) -}}
{{- if $limit -}}
{{- $heap := include "neo4j.toMi" .Values.jvm.heap.max | int -}}
{{- $cache := include "neo4j.toMi" .Values.jvm.pagecache | int -}}
{{- $total := add $heap $cache 256 -}}
{{- $have := include "neo4j.toMi" $limit | int -}}
{{- if gt $total $have -}}
{{- fail (printf "neo4j: heap %dMi plus page cache %dMi plus 256Mi of overhead is more than the %s memory limit, the pod would be killed under load" $heap $cache $limit) -}}
{{- end -}}
{{- end -}}
{{- end -}}
