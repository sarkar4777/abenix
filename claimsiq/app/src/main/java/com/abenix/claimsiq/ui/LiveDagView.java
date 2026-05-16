package com.abenix.claimsiq.ui;

import com.abenix.sdk.Abenix;
import com.abenix.sdk.DagSnapshot;
import com.abenix.sdk.WatchStream;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.vaadin.flow.component.AttachEvent;
import com.vaadin.flow.component.Component;
import com.vaadin.flow.component.DetachEvent;
import com.vaadin.flow.component.Html;
import com.vaadin.flow.component.Tag;
import com.vaadin.flow.component.UI;
import com.vaadin.flow.component.html.Div;
import com.vaadin.flow.component.html.H2;
import com.vaadin.flow.component.html.Span;
import com.vaadin.flow.component.orderedlayout.HorizontalLayout;
import com.vaadin.flow.component.orderedlayout.VerticalLayout;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.List;
import java.util.concurrent.atomic.AtomicReference;

/**
 * Live DAG renderer — subscribes to {@link Abenix#watch} for a
 * single execution and repaints the graph on every snapshot. Paper
 * palette + indigo accents to match the rest of ClaimsIQ.
 */
@Tag("claimsiq-live-dag")
public class LiveDagView extends VerticalLayout {

    private static final Logger log = LoggerFactory.getLogger(LiveDagView.class);
    private static final ObjectMapper JSON = new ObjectMapper().findAndRegisterModules();

    private final Abenix forge;
    private final String executionId;
    private final Div header = new Div();
    private final VerticalLayout nodeStack = new VerticalLayout();
    private final AtomicReference<WatchStream> streamRef = new AtomicReference<>();
    private UI attachedUi;

    public LiveDagView(Abenix forge, String executionId) {
        this.forge = forge;
        this.executionId = executionId;
        setPadding(false);
        setSpacing(false);
        setWidthFull();
        getStyle()
            .set("background", Palette.SURFACE)
            .set("border", "1px solid " + Palette.BORDER)
            .set("border-radius", "12px")
            .set("padding", "1.25rem 1.5rem")
            .set("box-shadow", "0 1px 2px rgba(15,23,42,0.04)");

        Div topTitle = new Div();
        Span eyebrow = new Span("ClaimsIQ · live pipeline");
        eyebrow.getStyle().set("font-size", "11px").set("text-transform", "uppercase")
            .set("letter-spacing", "0.1em").set("color", Palette.INDIGO).set("font-weight", "600").set("display", "block");
        topTitle.add(eyebrow);
        add(topTitle);

        header.getStyle().set("margin", "0.25rem 0 1rem 0");
        nodeStack.setPadding(false);
        nodeStack.setSpacing(false);
        nodeStack.setWidthFull();

        add(header, nodeStack);
        renderLoading();
    }

    @Override
    protected void onAttach(AttachEvent e) {
        super.onAttach(e);
        attachedUi = e.getUI();
        attachedUi.setPollInterval(2000);
        // Always paint the 6-node skeleton up front so the user sees the
        // pipeline shape (FNOL Intake → Policy Matcher → Damage Assessor →
        // Fraud Screener → Valuator → Claim Decider) before the first
        // SSE snapshot arrives. Real snapshots overwrite the skeleton
        // as soon as `dispatch()` fires.
        renderSkeleton();
        if (executionId == null || executionId.isBlank()) {
            return;
        }
        openStream();
    }

    @Override
    protected void onDetach(DetachEvent e) {
        super.onDetach(e);
        WatchStream s = streamRef.getAndSet(null);
        if (s != null) try { s.close(); } catch (Throwable ignored) {}
    }

    private void openStream() {
        try {
            WatchStream stream = forge.watch(executionId);
            streamRef.set(stream);
            stream.onSnapshot(this::dispatch);
            stream.onError(err -> dispatchError(err.getMessage()));
        } catch (Throwable t) {
            log.warn("Couldn't open watch stream for {}: {}", executionId, t.getMessage());
            dispatchError(t.getMessage());
        }
    }

    private void dispatch(DagSnapshot snap) {
        if (attachedUi == null) return;
        attachedUi.access(() -> render(snap));
    }

    private void dispatchError(String msg) {
        if (attachedUi == null) return;
        attachedUi.access(() -> {
            header.removeAll();
            H2 h = new H2("Couldn't connect to the live DAG stream.");
            h.getStyle().set("font-size", "15px").set("color", Palette.FAILED).set("margin", "0");
            Span s = new Span((msg == null ? "" : msg) + " · The claim row is saved — reload the page in a moment to retry.");
            s.getStyle().set("color", Palette.TEXT_BODY).set("font-size", "12.5px");
            header.add(h, s);
        });
    }

    private void renderLoading() {
        header.removeAll();
        H2 h = new H2("Connecting to pipeline…");
        h.getStyle().set("font-size", "15px").set("color", Palette.TEXT_STRONG).set("margin", "0");
        Span s = new Span("Subscribing to the Abenix execution stream.");
        s.getStyle().set("color", Palette.TEXT_MUTED).set("font-size", "12.5px");
        header.add(h, s);
    }

    /**
     * Paint the full 6-node ClaimsIQ pipeline shape with every node in
     * {@code pending} state — runs immediately on attach so users see
     * the pipeline structure before the first SSE snapshot lands.
     * Real snapshots replace this skeleton on the next {@link #render}.
     */
    private void renderSkeleton() {
        header.removeAll();
        H2 h = new H2("ClaimsIQ — Adjudicate Claim");
        h.getStyle().set("font-size", "16px").set("color", Palette.TEXT_STRONG).set("margin", "0")
            .set("letter-spacing", "-0.02em");
        HorizontalLayout meta = new HorizontalLayout();
        meta.setSpacing(true);
        meta.getStyle().set("margin-top", "0.5rem").set("flex-wrap", "wrap");
        meta.add(chip("status", "queued", Palette.AMBER));
        meta.add(chip("progress", "0 / 6", Palette.INDIGO));
        header.add(h, meta);

        nodeStack.removeAll();
        // (id, label, agent_slug) tuples — labels are the user-facing
        // names from the FNOL form / detail view, slugs match the
        // platform seeds under packages/db/seeds/agents/cq_*.yaml.
        String[][] skeleton = {
            {"fnol",          "FNOL Intake",      "claimsiq-fnol-intake"},
            {"policy_match",  "Policy Matcher",   "claimsiq-policy-matcher"},
            {"damage_assess", "Damage Assessor",  "claimsiq-damage-assessor"},
            {"fraud_screen",  "Fraud Screener",   "claimsiq-fraud-screener"},
            {"valuate",       "Valuator",         "claimsiq-valuator"},
            {"decide",        "Claim Decider",    "claimsiq-claim-decider"},
        };
        for (String[] row : skeleton) {
            DagSnapshot.Node n = new DagSnapshot.Node(
                row[0], row[1], null, row[2], "pending",
                null, null, null, null, null, null, null, null, null, null
            );
            nodeStack.add(renderNode(n));
        }
    }

    private void render(DagSnapshot snap) {
        header.removeAll();

        H2 h = new H2(snap.agentName() != null ? snap.agentName() : "Pipeline");
        h.getStyle().set("font-size", "16px").set("color", Palette.TEXT_STRONG).set("margin", "0")
            .set("letter-spacing", "-0.02em");

        HorizontalLayout meta = new HorizontalLayout();
        meta.setSpacing(true);
        meta.getStyle().set("margin-top", "0.5rem").set("flex-wrap", "wrap");
        meta.add(chip("status", snap.status() == null ? "—" : snap.status(), tone(snap.status())));
        if (snap.progress() != null) {
            meta.add(chip("progress",
                snap.progress().completed() + " / " + snap.progress().total(),
                Palette.INDIGO));
        }
        if (snap.costSoFar() != null) {
            meta.add(chip("cost", String.format("$%.4f", snap.costSoFar()), Palette.VIOLET));
        }
        if (snap.tokens() != null) {
            meta.add(chip("tokens",
                snap.tokens().in() + " in / " + snap.tokens().out() + " out",
                Palette.TEXT_MUTED));
        }
        header.add(h, meta);

        nodeStack.removeAll();
        List<DagSnapshot.Node> nodes = snap.nodes() == null ? List.of() : snap.nodes();
        for (DagSnapshot.Node n : nodes) {
            nodeStack.add(renderNode(n));
        }
    }

    private Component renderNode(DagSnapshot.Node n) {
        Div card = new Div();
        String color = tone(n.status());
        card.getStyle()
            .set("display", "grid")
            .set("grid-template-columns", "28px 1fr auto")
            .set("gap", "0.85rem")
            .set("padding", "0.75rem 0.9rem")
            .set("margin-bottom", "0.5rem")
            .set("background", Palette.SURFACE)
            .set("border", "1px solid " + color + "40")
            .set("border-left", "4px solid " + color)
            .set("border-radius", "10px");

        Span bullet = new Span();
        bullet.getStyle()
            .set("width", "12px").set("height", "12px")
            .set("border-radius", "999px")
            .set("background", color)
            .set("margin-top", "5px")
            .set("box-shadow", "0 0 0 4px " + color + "25");

        VerticalLayout body = new VerticalLayout();
        body.setPadding(false);
        body.setSpacing(false);

        Span label = new Span(n.label() == null ? n.id() : n.label());
        label.getStyle().set("color", Palette.TEXT_STRONG).set("font-weight", "700").set("font-size", "14px");

        Span meta = new Span(
            (n.agentSlug() != null ? n.agentSlug() + " · " : "")
            + (n.toolName() == null ? "" : n.toolName())
        );
        meta.getStyle().set("color", Palette.TEXT_SUBTLE).set("font-size", "11px")
            .set("font-family", "ui-monospace, Menlo, monospace");

        body.add(label, meta);

        if (n.input() != null || n.output() != null || (n.toolCalls() != null && !n.toolCalls().isEmpty())) {
            Html io = new Html(renderIoBlock(n));
            body.add(io);
        }

        Span statusChip = chip("", n.status() == null ? "—" : n.status(), color);
        statusChip.getStyle().set("align-self", "start");

        card.add(bullet, body, statusChip);
        return card;
    }

    private String renderIoBlock(DagSnapshot.Node n) {
        StringBuilder sb = new StringBuilder();
        sb.append("<details style=\"margin-top:0.5rem;\">");
        sb.append("<summary style=\"cursor:pointer;color:").append(Palette.INDIGO)
            .append(";font-size:10.5px;text-transform:uppercase;letter-spacing:0.1em;font-weight:600;\">")
            .append("input + output</summary>");
        sb.append("<div style=\"display:grid;grid-template-columns:1fr 1fr;gap:0.75rem;margin-top:0.5rem;\">");
        sb.append("<div><div style=\"font-size:9.5px;color:").append(Palette.TEXT_SUBTLE)
            .append(";text-transform:uppercase;letter-spacing:0.1em;font-weight:600;\">input</div>");
        sb.append("<pre style=\"white-space:pre-wrap;word-break:break-word;background:").append(Palette.SURFACE_SUNKEN)
            .append(";border:1px solid ").append(Palette.BORDER)
            .append(";padding:0.55rem;border-radius:6px;font-size:11px;color:").append(Palette.TEXT_BODY)
            .append(";margin-top:0.25rem;max-height:240px;overflow:auto;\">");
        sb.append(escape(pretty(n.input())));
        sb.append("</pre></div>");
        sb.append("<div><div style=\"font-size:9.5px;color:").append(Palette.TEXT_SUBTLE)
            .append(";text-transform:uppercase;letter-spacing:0.1em;font-weight:600;\">output</div>");
        sb.append("<pre style=\"white-space:pre-wrap;word-break:break-word;background:").append(Palette.SURFACE_SUNKEN)
            .append(";border:1px solid ").append(Palette.BORDER)
            .append(";padding:0.55rem;border-radius:6px;font-size:11px;color:").append(Palette.TEXT_BODY)
            .append(";margin-top:0.25rem;max-height:240px;overflow:auto;\">");
        sb.append(escape(pretty(n.output())));
        sb.append("</pre></div>");
        sb.append("</div>");
        if (n.error() != null && !n.error().isBlank()) {
            sb.append("<div style=\"margin-top:0.5rem;padding:0.55rem;background:").append(Palette.FAILED_SOFT)
                .append(";border:1px solid ").append(Palette.FAILED).append("40;")
                .append("border-radius:6px;font-size:11.5px;color:").append(Palette.FAILED).append(";\">");
            sb.append(escape(n.error())).append("</div>");
        }
        sb.append("</details>");
        return sb.toString();
    }

    private static String pretty(Object o) {
        if (o == null) return "(none)";
        try {
            return JSON.writerWithDefaultPrettyPrinter().writeValueAsString(o);
        } catch (Exception e) {
            return String.valueOf(o);
        }
    }

    private static String escape(String s) {
        if (s == null) return "";
        return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;");
    }

    private static Span chip(String label, String value, String color) {
        Span c = new Span();
        c.getElement().setProperty("innerHTML",
            (label.isBlank() ? "" :
                "<span style=\"color:" + color + "99;font-size:9.5px;text-transform:uppercase;"
                + "letter-spacing:0.1em;margin-right:4px;font-weight:600;\">" + label + "</span>")
            + "<span style=\"color:" + color + ";font-weight:700;\">" + escape(value) + "</span>"
        );
        c.getStyle()
            .set("padding", "3px 9px")
            .set("border-radius", "999px")
            .set("font-size", "11px")
            .set("background", color + "15")
            .set("border", "1px solid " + color + "35");
        return c;
    }

    private static String tone(String status) {
        if (status == null) return Palette.TEXT_MUTED;
        return switch (status) {
            case "completed"   -> Palette.APPROVED;
            case "running"     -> Palette.INDIGO;
            case "failed"      -> Palette.FAILED;
            case "skipped"     -> Palette.VIOLET;
            case "pending"     -> Palette.TEXT_MUTED;
            case "queued"      -> Palette.AMBER;
            default            -> Palette.TEXT_MUTED;
        };
    }
}
