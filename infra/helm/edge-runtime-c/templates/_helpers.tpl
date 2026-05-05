{{- define "edge-runtime-c.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "edge-runtime-c.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}

{{- define "edge-runtime-c.labels" -}}
helm.sh/chart: {{ include "edge-runtime-c.name" . }}-{{ .Chart.Version }}
app.kubernetes.io/name: {{ include "edge-runtime-c.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
abenix.io/gateway-id: {{ .Values.gateway_id | quote }}
abenix.io/runtime-variant: "c"
{{- end }}

{{- define "edge-runtime-c.selectorLabels" -}}
app.kubernetes.io/name: {{ include "edge-runtime-c.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}
