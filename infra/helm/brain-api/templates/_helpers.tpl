{{- define "brain-api.fullname" -}}
{{- .Release.Name }}-brain-api
{{- end }}

{{- define "brain-api.labels" -}}
app.kubernetes.io/name: brain-api
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{- define "brain-api.selectorLabels" -}}
app.kubernetes.io/name: brain-api
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}
