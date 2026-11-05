{{- define "edge-runtime.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "edge-runtime.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}

{{- define "edge-runtime.labels" -}}
helm.sh/chart: {{ include "edge-runtime.name" . }}-{{ .Chart.Version }}
app.kubernetes.io/name: {{ include "edge-runtime.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
abenix.io/gateway-id: {{ .Values.gateway_id | quote }}
{{- end }}

{{- define "edge-runtime.selectorLabels" -}}
app.kubernetes.io/name: {{ include "edge-runtime.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{- define "edge-runtime.validate" -}}
{{- if not (has .Values.mode (list "legacy" "gateway")) -}}
{{- fail "mode must be legacy or gateway" -}}
{{- end -}}
{{- if and (eq .Values.mode "legacy") (not .Values.signing_pubkey) (not (eq (toString .Values.allow_unsigned) "true")) -}}
{{- fail "signing_pubkey is required in legacy mode. Fetch it from GET /api/edge/signing-key on the platform. allow_unsigned=true bypasses this for local development only." -}}
{{- end -}}
{{- end }}

{{- define "edge-runtime.literalTrue" -}}
{{- if eq (toString .) "true" -}}true{{- else -}}false{{- end -}}
{{- end }}
