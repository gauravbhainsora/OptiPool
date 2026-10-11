{{- define "optipool.name" -}}
{{ .Release.Name }}-optipool
{{- end -}}
{{- define "optipool.labels" -}}
app.kubernetes.io/name: optipool
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | quote }}
{{- end -}}
{{- define "optipool.sa" -}}
{{ default (include "optipool.name" .) .Values.serviceAccount.name }}
{{- end -}}
