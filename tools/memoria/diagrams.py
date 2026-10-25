# ruff: noqa: N803, C408
"""Genera los diagramas PNG de la memoria (docs/img)."""

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch


def build_diagrams(OUT):

    def box(ax, x, y, w, h, text, fc="#e8f0fe", ec="#1a56db", fs=8, bold=False):
        ax.add_patch(
            FancyBboxPatch(
                (x, y), w, h, boxstyle="round,pad=0.02,rounding_size=0.08", fc=fc, ec=ec, lw=1.2
            )
        )
        ax.text(
            x + w / 2,
            y + h / 2,
            text,
            ha="center",
            va="center",
            fontsize=fs,
            fontweight="bold" if bold else "normal",
            wrap=True,
        )

    def arrow(ax, x1, y1, x2, y2, text=None):
        ax.annotate(
            "",
            xy=(x2, y2),
            xytext=(x1, y1),
            arrowprops=dict(arrowstyle="->", color="#374151", lw=1.2),
        )
        if text:
            ax.text(
                (x1 + x2) / 2, (y1 + y2) / 2 + 0.12, text, ha="center", fontsize=7, color="#374151"
            )

    # 1. Arquitectura
    fig, ax = plt.subplots(figsize=(9, 5.6))
    ax.set_xlim(0, 12)
    ax.set_ylim(0, 7.4)
    ax.axis("off")
    box(ax, 0.1, 6.2, 2.9, 0.9, "Usuario\nTelegram (chat + Mini App)", "#fef3c7", "#b45309")
    box(ax, 4.0, 6.2, 4.0, 0.9, "Nginx Proxy Manager\n(HTTPS, EC2 AWS)", "#f3f4f6", "#4b5563")
    box(ax, 9.2, 6.2, 2.6, 0.9, "LLM OpenAI-compatible\n(API externa)", "#fce7f3", "#be185d")
    ax.add_patch(
        FancyBboxPatch(
            (0.2, 2.0),
            8.2,
            3.8,
            boxstyle="round,pad=0.02",
            fc="#f9fafb",
            ec="#1a56db",
            lw=1.5,
            ls="--",
        )
    )
    ax.text(
        0.4,
        5.55,
        "FitCoachIA (monolito modular FastAPI, contenedor Docker)",
        fontsize=8,
        color="#1a56db",
        fontweight="bold",
    )
    box(ax, 0.5, 4.3, 1.9, 0.9, "api\nwebhook, /health,\nMini App, admin")
    box(ax, 2.7, 4.3, 2.3, 0.9, "service\nConversationService,\nTraining, Cuotas")
    box(ax, 5.3, 4.3, 2.8, 0.9, "service/agent\nInterviewer · Trainer ·\nCurator · Evaluador")
    box(
        ax,
        2.7,
        2.9,
        2.3,
        0.9,
        "domain\nentidades, errores,\ntextos (constants)",
        "#dcfce7",
        "#15803d",
    )
    box(ax, 0.5, 2.9, 1.9, 0.9, "repository\n(puertos Protocol)", "#dcfce7", "#15803d")
    box(
        ax,
        5.3,
        2.9,
        2.8,
        0.9,
        "infrastructure\nbot, database, vectordb,\njobs, observability",
        "#ede9fe",
        "#6d28d9",
    )
    box(
        ax,
        0.5,
        2.15,
        7.6,
        0.5,
        "Scheduler asyncio: recordatorios de fin de ciclo y encuestas semanales",
        "#ede9fe",
        "#6d28d9",
        fs=7,
    )
    box(ax, 9.2, 4.6, 2.6, 0.9, "Embedder\nall-MiniLM-L6-v2\n(384 dim)", "#e0f2fe", "#0369a1")
    box(
        ax,
        9.2,
        3.2,
        2.6,
        0.9,
        "PostgreSQL + pgVector\ncatálogo de ejercicios\n(solo lectura)",
        "#e0f2fe",
        "#0369a1",
    )
    box(
        ax,
        9.2,
        1.8,
        2.6,
        0.9,
        "PostgreSQL\nconversaciones, perfiles,\nplanes, tokens (Alembic)",
        "#e0f2fe",
        "#0369a1",
    )
    box(
        ax,
        0.2,
        0.2,
        11.6,
        1.1,
        "Observabilidad: OpenTelemetry → Collector → Tempo / Loki / Prometheus → Grafana"
        "   ·   Backups Postgres → S3",
        "#f3f4f6",
        "#4b5563",
    )
    arrow(ax, 3.0, 6.75, 4.0, 6.75)
    arrow(ax, 4.0, 6.5, 3.0, 6.5)
    arrow(ax, 6.0, 6.2, 4.0, 5.4)
    arrow(ax, 2.4, 4.75, 2.7, 4.75)
    arrow(ax, 5.0, 4.75, 5.3, 4.75)
    arrow(ax, 8.1, 4.9, 9.2, 5.0)
    arrow(ax, 8.1, 3.3, 9.2, 3.6)
    arrow(ax, 8.1, 4.5, 9.2, 6.3)
    arrow(ax, 8.1, 3.1, 9.2, 2.3)
    fig.savefig(f"{OUT}/arquitectura.png", dpi=170, bbox_inches="tight")
    plt.close(fig)

    # 2. Flujo del plan (RAG)
    fig, ax = plt.subplots(figsize=(9, 2.8))
    ax.set_xlim(0, 12)
    ax.set_ylim(0, 3.4)
    ax.axis("off")
    steps = [
        ("/interview\nEntrevistador\n→ perfil JSON", "#fef3c7", "#b45309"),
        ("/train\nconsulta por\ngrupo muscular", "#e8f0fe", "#1a56db"),
        ("Embedder +\npgVector\n(coseno, filtros)", "#e0f2fe", "#0369a1"),
        ("Entrenador\n1 llamada LLM\n(catálogo anclado)", "#fce7f3", "#be185d"),
        ("Validación\nJSON/IDs +\n1 reparación", "#dcfce7", "#15803d"),
        ("Borrador →\nconfirmar →\nplan 4 semanas", "#ede9fe", "#6d28d9"),
    ]
    w, gap = 1.6, 0.3
    for i, (t, fc, ec) in enumerate(steps):
        x = 0.2 + i * (w + gap)
        box(ax, x, 1.2, w, 1.5, t, fc, ec, fs=8)
        if i:
            arrow(ax, x - gap, 1.95, x, 1.95)
    box(
        ax,
        0.2,
        0.1,
        11.4,
        0.6,
        "Después: preguntas sobre el plan (sin RAG) · revisión de fin de ciclo · sustitución de ejercicios · encuestas semanales",
        "#f3f4f6",
        "#4b5563",
        fs=7,
    )
    fig.savefig(f"{OUT}/flujo-plan.png", dpi=170, bbox_inches="tight")
    plt.close(fig)

    # 3. CI/CD
    fig, ax = plt.subplots(figsize=(9, 3.2))
    ax.set_xlim(0, 12)
    ax.set_ylim(0, 4)
    ax.axis("off")
    cols = [
        ("pre-commit\nruff · gitleaks\nbandit · cfn-lint", "#fef3c7", "#b45309"),
        ("build.yml\ncalidad+mypy+audit\n→ Semgrep → tests", "#e8f0fe", "#1a56db"),
        ("PR a develop /\nmain (validate-*)", "#f3f4f6", "#4b5563"),
        ("release.yml\n(manual) imagen +\nTrivy + GitHub release", "#fce7f3", "#be185d"),
        ("deploy.yml\nrsync + make up\nen EC2", "#dcfce7", "#15803d"),
    ]
    w, gap = 1.95, 0.4
    for i, (t, fc, ec) in enumerate(cols):
        x = 0.1 + i * (w + gap)
        box(ax, x, 1.6, w, 1.6, t, fc, ec, fs=7.5)
        if i:
            arrow(ax, x - gap, 2.4, x, 2.4)
    box(
        ax,
        0.1,
        0.3,
        11.8,
        0.8,
        "Gate de cobertura ≥ 80 % (unit + IT con Postgres, pgVector y stub de Telegram/LLM/embedder en Docker)",
        "#f3f4f6",
        "#4b5563",
        fs=7.5,
    )
    fig.savefig(f"{OUT}/cicd.png", dpi=170, bbox_inches="tight")
    plt.close(fig)
