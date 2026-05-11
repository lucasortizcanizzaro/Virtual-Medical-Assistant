import os
import smtplib
import sys
from datetime import datetime, timezone
from email.message import EmailMessage

from consultas import AsistenteMedico


DEFAULT_QUERY = "Tengo dolor de cabeza y fiebre leve desde hoy."

NO_RESULTS_MARKER = "No encontré condiciones que coincidan con los síntomas descritos."


def _require_env(var_name: str) -> str:
    value = os.getenv(var_name, "").strip()
    if not value:
        raise RuntimeError(f"Falta la variable de entorno requerida: {var_name}")
    return value


def _send_alert_email(subject: str, body: str) -> None:
    """Envía un email de alerta si las variables SMTP están configuradas."""
    to_addr = os.getenv("ALERT_EMAIL_TO", "").strip()
    if not to_addr:
        print("[keepalive] alert_email=skipped (ALERT_EMAIL_TO no configurado)", file=sys.stderr)
        return

    from_addr = os.getenv("ALERT_EMAIL_FROM", to_addr).strip()
    smtp_host = os.getenv("SMTP_HOST", "").strip()
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_user = os.getenv("SMTP_USER", "").strip()
    smtp_password = os.getenv("SMTP_PASSWORD", "").strip()

    if not smtp_host:
        print("[keepalive] alert_email=skipped (SMTP_HOST no configurado)", file=sys.stderr)
        return

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = to_addr
    msg.set_content(body)

    try:
        with smtplib.SMTP(smtp_host, smtp_port, timeout=15) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            if smtp_user and smtp_password:
                server.login(smtp_user, smtp_password)
            server.send_message(msg)
        print(f"[keepalive] alert_email=sent to={to_addr}")
    except Exception as mail_exc:
        print(f"[keepalive] alert_email=failed error={mail_exc}", file=sys.stderr)


def main() -> int:
    # Validar secretos minimos para que el job falle de forma explicita si falta algo.
    _require_env("GEMINI_API_KEY")
    _require_env("NEO4J_URI")
    _require_env("NEO4J_USERNAME")
    _require_env("NEO4J_PASSWORD")

    query = os.getenv("KEEPALIVE_QUERY", DEFAULT_QUERY).strip() or DEFAULT_QUERY
    started = datetime.now(timezone.utc).isoformat()
    print(f"[keepalive] start={started}")
    print(f"[keepalive] query={query}")

    asistente = AsistenteMedico()
    try:
        respuesta, _ = asistente.preguntar(query, historial=[], contexto_diferencial=None)
        print("[keepalive] ok=true")
        print(f"[keepalive] respuesta_chars={len(respuesta)}")
        print(f"[keepalive] respuesta_preview={respuesta[:220].replace(chr(10), ' ')}")

        if NO_RESULTS_MARKER in respuesta:
            print("[keepalive] alert=no_results", file=sys.stderr)
            _send_alert_email(
                subject="[AgenteSintomas] Keepalive: sin resultados para los síntomas",
                body=(
                    f"El agente no encontró condiciones para la consulta de keepalive.\n\n"
                    f"Query: {query}\n\n"
                    f"Respuesta del agente:\n{respuesta}\n\n"
                    f"Timestamp: {started}"
                ),
            )
    except Exception as exc:
        print(f"[keepalive] ok=false error={exc}", file=sys.stderr)
        _send_alert_email(
            subject=f"[AgenteSintomas] Keepalive: error — {type(exc).__name__}",
            body=(
                f"El job de keepalive falló con una excepción.\n\n"
                f"Query: {query}\n\n"
                f"Error: {exc}\n\n"
                f"Timestamp: {started}"
            ),
        )
        raise
    finally:
        asistente.cerrar()

    finished = datetime.now(timezone.utc).isoformat()
    print(f"[keepalive] end={finished}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"[keepalive] ok=false error={exc}", file=sys.stderr)
        raise
