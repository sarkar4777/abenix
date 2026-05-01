package com.abenix.claimsiq.ui;

import com.abenix.claimsiq.domain.Claim;
import com.abenix.claimsiq.service.ClaimsService;
import com.abenix.claimsiq.service.SamplePhotos;
import com.vaadin.flow.component.Html;
import com.vaadin.flow.component.UI;
import com.vaadin.flow.component.button.Button;
import com.vaadin.flow.component.button.ButtonVariant;
import com.vaadin.flow.component.html.Div;
import com.vaadin.flow.component.html.H1;
import com.vaadin.flow.component.html.H2;
import com.vaadin.flow.component.html.H3;
import com.vaadin.flow.component.html.Span;
import com.vaadin.flow.component.icon.VaadinIcon;
import com.vaadin.flow.component.notification.Notification;
import com.vaadin.flow.component.orderedlayout.HorizontalLayout;
import com.vaadin.flow.component.orderedlayout.VerticalLayout;
import com.vaadin.flow.router.PageTitle;
import com.vaadin.flow.router.Route;
import com.vaadin.flow.router.RouteParam;
import com.vaadin.flow.router.RouteParameters;

import java.util.List;

@Route(value = "", layout = MainLayout.class)
@PageTitle("ClaimsIQ · Dashboard")
public class DashboardView extends VerticalLayout {

    private static final String SAMPLE_DESC =
        "Tuesday evening around 6pm I was rear-ended at a stop light on I-5 near exit 168. "
        + "Other driver admitted fault and waited for police. No injuries on either side. "
        + "My rear bumper is crushed inward and the trunk lid won't close — I can see the inner panel is bent. "
        + "I've attached the photos I took at the scene. I need this fixed quickly — it's my only way to work.";

    private final SamplePhotos samples;

    public DashboardView(ClaimsService service, SamplePhotos samples) {
        this.samples = samples;
        setSizeFull();
        setPadding(true);
        setSpacing(true);
        getStyle().set("max-width", "1180px").set("margin", "0 auto").set("padding", "2rem");

        add(header(service));
        add(heroCard(service));
        add(metrics(service.listRecent()));
        add(pipelineCard());
        add(toolsCard());
        add(credsCard());
    }

    private HorizontalLayout header(ClaimsService service) {
        Div titleStack = new Div();
        titleStack.getStyle().set("display", "flex").set("flex-direction", "column");

        Span eyebrow = new Span("ClaimsIQ · overview");
        eyebrow.getStyle().set("font-size", "11px").set("text-transform", "uppercase")
            .set("letter-spacing", "0.1em").set("color", Palette.INDIGO);

        H1 h = new H1("Insurance claims, adjudicated in under a minute.");
        h.getStyle().set("color", Palette.TEXT_STRONG).set("margin", "0.25rem 0 0 0")
            .set("font-size", "30px").set("letter-spacing", "-0.025em").set("line-height", "1.15");

        Span sub = new Span("Every First Notice of Loss runs through a six-agent pipeline: classification, policy match, multimodal damage grading, fraud screen, valuation, and a decision with cited clauses + a draft claimant letter.");
        sub.getStyle().set("color", Palette.TEXT_BODY).set("font-size", "14px")
            .set("margin-top", "0.5rem").set("max-width", "760px").set("line-height", "1.55");

        titleStack.add(eyebrow, h, sub);

        Button walk = new Button("Walkthrough", VaadinIcon.LIGHTBULB.create());
        walk.getStyle().set("color", Palette.INDIGO);
        walk.addClickListener(e -> walk.getUI().ifPresent(ui -> ui.navigate(HelpView.class)));

        Button cta = new Button("File a FNOL", VaadinIcon.FILE_ADD.create());
        cta.addThemeVariants(ButtonVariant.LUMO_PRIMARY);
        cta.getStyle()
            .set("background", Palette.INDIGO).set("color", "white")
            .set("box-shadow", "0 4px 14px " + Palette.INDIGO + "40");
        cta.addClickListener(e -> cta.getUI().ifPresent(ui -> ui.navigate(FnolView.class)));

        HorizontalLayout row = new HorizontalLayout(titleStack, walk, cta);
        row.setWidthFull();
        row.setAlignItems(Alignment.CENTER);
        row.setSpacing(true);
        row.expand(titleStack);
        return row;
    }

    private Div heroCard(ClaimsService service) {
        Div card = new Div();
        card.getStyle()
            .set("background", "linear-gradient(120deg, " + Palette.INDIGO_SOFT + ", #F3EFFE)")
            .set("border", "1px solid " + Palette.INDIGO_EDGE)
            .set("border-radius", "14px")
            .set("padding", "1.5rem 1.75rem");

        Span eyebrow = new Span("New here?");
        eyebrow.getStyle().set("font-size", "11px").set("text-transform", "uppercase")
            .set("letter-spacing", "0.1em").set("color", Palette.INDIGO).set("font-weight", "600");

        H2 h = new H2("Run a claim end-to-end in about 45 seconds.");
        h.getStyle().set("color", Palette.TEXT_STRONG).set("margin", "0.25rem 0 0.5rem 0")
            .set("font-size", "22px").set("letter-spacing", "-0.02em");

        Span body = new Span(
            "Click the button below — we'll file a realistic rear-end-collision FNOL, "
            + "fire the six-agent pipeline against it, and drop you on the claim detail "
            + "with the live DAG streaming as each node finishes. The claimant letter, "
            + "policy citations, and fraud risk tier appear as the pipeline closes."
        );
        body.getStyle().set("color", Palette.TEXT_BODY).set("font-size", "13.5px")
            .set("line-height", "1.55").set("display", "block").set("max-width", "720px");

        Button go = new Button("Try it now — sample FNOL + live pipeline", VaadinIcon.PLAY_CIRCLE.create());
        go.addThemeVariants(ButtonVariant.LUMO_PRIMARY);
        go.getStyle()
            .set("margin-top", "1rem")
            .set("background", Palette.INDIGO).set("color", "white");
        go.addClickListener(e -> {
            try {
                // Attach the 3 baked-in damage photos so the multimodal
                // Damage Assessor has something to chew on. The CSV
                // shape matches what FnolView sends.
                String photosCsv = samples.asCsv();
                Claim c = service.ingest(new ClaimsService.FnolRequest(
                    "Alex Rivera", "POL-2024-77321", "web", SAMPLE_DESC, photosCsv));
                Notification.show("Sample FNOL filed with 3 demo photos — pipeline is running.", 2500,
                    Notification.Position.BOTTOM_END);
                // Use string nav: the @Route is "claims/:id" and the
                // RouteParameters/RouteParam API doesn't always match it
                // cleanly — string nav routes through the same dispatcher
                // and lets HasUrlParameter pick up the segment.
                UI.getCurrent().navigate("claims/" + c.getId());
            } catch (Throwable t) {
                Notification.show("Couldn't file the sample claim: " + t.getMessage(), 4000,
                    Notification.Position.MIDDLE);
            }
        });

        Button open = new Button("…or open the FNOL form", VaadinIcon.FILE_ADD.create());
        open.addThemeVariants(ButtonVariant.LUMO_TERTIARY);
        open.getStyle().set("margin-top", "1rem").set("margin-left", "0.5rem")
            .set("color", Palette.INDIGO);
        open.addClickListener(e -> open.getUI().ifPresent(ui -> ui.navigate(FnolView.class)));

        card.add(eyebrow, h, body, new HorizontalLayout(go, open));
        return card;
    }

    private HorizontalLayout metrics(List<Claim> all) {
        long total = all.size();
        long approved = all.stream().filter(c -> "approved".equals(c.getStatus()) || "partial".equals(c.getStatus())).count();
        long denied = all.stream().filter(c -> "denied".equals(c.getStatus())).count();
        long routed = all.stream().filter(c -> "routed_to_human".equals(c.getStatus())).count();
        long failed = all.stream().filter(c -> "failed".equals(c.getStatus())).count();
        double totalSpend = all.stream().mapToDouble(c -> c.getCostUsd() == null ? 0 : c.getCostUsd()).sum();

        HorizontalLayout row = new HorizontalLayout(
            metric("Claims filed", String.valueOf(total), Palette.INDIGO),
            metric("Auto-approved", String.valueOf(approved), Palette.APPROVED),
            metric("Denied", String.valueOf(denied), Palette.DENIED),
            metric("Routed to adjuster", String.valueOf(routed), Palette.AMBER),
            metric("Pipeline failures", String.valueOf(failed), Palette.FAILED),
            metric("LLM spend", String.format("$%.4f", totalSpend), Palette.VIOLET)
        );
        row.setWidthFull();
        row.setSpacing(true);
        return row;
    }

    private Div metric(String label, String value, String color) {
        Div d = new Div();
        d.getStyle()
            .set("flex", "1").set("padding", "1rem 1.1rem")
            .set("background", Palette.SURFACE)
            .set("border", "1px solid " + Palette.BORDER)
            .set("border-radius", "12px")
            .set("box-shadow", "0 1px 2px rgba(15,23,42,0.04)");
        Span l = new Span(label);
        l.getStyle()
            .set("font-size", "10.5px").set("text-transform", "uppercase")
            .set("letter-spacing", "0.1em").set("color", Palette.TEXT_SUBTLE)
            .set("font-weight", "600");
        Div v = new Div();
        v.setText(value);
        v.getStyle().set("font-size", "24px").set("font-weight", "700")
            .set("color", color).set("margin-top", "0.35rem").set("letter-spacing", "-0.02em");
        d.add(l, v);
        return d;
    }

    private Div pipelineCard() {
        Div card = new Div();
        card.getStyle()
            .set("background", Palette.SURFACE)
            .set("border", "1px solid " + Palette.BORDER)
            .set("border-radius", "14px")
            .set("padding", "1.5rem 1.75rem");

        Span eyebrow = new Span("How the adjudication pipeline works");
        eyebrow.getStyle().set("font-size", "11px").set("text-transform", "uppercase")
            .set("letter-spacing", "0.1em").set("color", Palette.AMBER).set("font-weight", "600");

        H2 h = new H2("Six agents, one decision.");
        h.getStyle().set("color", Palette.TEXT_STRONG).set("margin", "0.25rem 0 1rem 0")
            .set("font-size", "22px").set("letter-spacing", "-0.02em");

        Div flowGrid = new Div();
        flowGrid.getStyle()
            .set("display", "grid")
            .set("grid-template-columns", "repeat(auto-fit, minmax(240px, 1fr))")
            .set("gap", "0.75rem");

        flowGrid.add(
            flowStep("1", "FNOL Intake", "Classifies claim type, PII-redacts, assigns urgency 1-5.", "text_analyzer · pii_redactor · moderation"),
            flowStep("2", "Policy Matcher", "Hybrid search over the policy KB, returns sections, exclusions, deductible, limit.", "knowledge_search"),
            flowStep("3", "Damage Assessor", "MULTIMODAL — grades every photo 0-100 for severity, flags staged-damage inconsistencies.", "image_analyzer · market_data"),
            flowStep("4", "Fraud Screener", "Adverse media + OFAC + PEP on involved parties; pattern heuristics on timing + geography.", "adverse_media · sanctions_screening · pep_screening"),
            flowStep("5", "Valuator", "ACV math with deductible + limit cap; pulls comparables for total-loss valuations.", "financial_calculator · market_data · code_executor"),
            flowStep("6", "Claim Decider", "Synthesises decision, drafts claimant letter + adjuster notes, every coverage argument cites a policy clause.", "moderation")
        );

        card.add(eyebrow, h, flowGrid);
        return card;
    }

    private Div flowStep(String n, String title, String body, String tools) {
        Div card = new Div();
        card.getStyle()
            .set("border", "1px solid " + Palette.BORDER)
            .set("border-radius", "10px")
            .set("padding", "0.85rem 1rem")
            .set("background", Palette.PAGE_BG);

        HorizontalLayout top = new HorizontalLayout();
        top.setSpacing(true);
        top.setAlignItems(Alignment.CENTER);
        Div num = new Div();
        num.setText(n);
        num.getStyle()
            .set("width", "24px").set("height", "24px")
            .set("border-radius", "999px")
            .set("background", Palette.INDIGO).set("color", "white")
            .set("display", "flex").set("align-items", "center").set("justify-content", "center")
            .set("font-weight", "700").set("font-size", "12px").set("flex-shrink", "0");
        Span t = new Span(title);
        t.getStyle().set("color", Palette.TEXT_STRONG).set("font-weight", "600").set("font-size", "14px");
        top.add(num, t);

        Span b = new Span(body);
        b.getStyle().set("color", Palette.TEXT_BODY).set("font-size", "12.5px")
            .set("line-height", "1.5").set("display", "block").set("margin-top", "0.5rem");

        Span tl = new Span(tools);
        tl.getStyle().set("color", Palette.TEXT_SUBTLE).set("font-size", "11px")
            .set("font-family", "ui-monospace, Menlo, monospace").set("display", "block")
            .set("margin-top", "0.5rem");

        card.add(top, b, tl);
        return card;
    }

    private Div toolsCard() {
        Div card = new Div();
        card.getStyle()
            .set("background", Palette.AMBER_SOFT)
            .set("border", "1px solid " + Palette.AMBER_EDGE)
            .set("border-radius", "14px")
            .set("padding", "1.5rem 1.75rem");

        Span eyebrow = new Span("Newer + diverse tools this demo exercises");
        eyebrow.getStyle().set("font-size", "11px").set("text-transform", "uppercase")
            .set("letter-spacing", "0.1em").set("color", Palette.AMBER).set("font-weight", "600");

        H3 h = new H3("Beyond \"just an LLM\".");
        h.getStyle().set("color", Palette.TEXT_STRONG).set("margin", "0.25rem 0 0.5rem 0")
            .set("font-size", "18px").set("letter-spacing", "-0.02em");

        Html body = new Html(
            "<div style=\"color:#3f3b60;font-size:13px;line-height:1.6;\">" +
            "<p style=\"margin:0;\">ClaimsIQ is a showcase for tools you can't easily bolt onto a vanilla LLM prompt:</p>" +
            "<ul style=\"margin-top:0.5rem;padding-left:1.25rem;\">" +
            "<li><strong>image_analyzer</strong> — each damage photo gets a structured vision pass (affected components, severity score, staged-damage heuristics).</li>" +
            "<li><strong>adverse_media · sanctions_screening · pep_screening</strong> — three parallel watchlist hits on every named party before a dollar moves.</li>" +
            "<li><strong>financial_calculator · code_executor</strong> — deterministic ACV math with every step auditable; no hallucinated numbers.</li>" +
            "<li><strong>knowledge_search</strong> — hybrid retrieval over a policy KB; every coverage argument carries a <code>policy_id@version</code> reference.</li>" +
            "<li><strong>moderation</strong> — post-LLM filter on the claimant letter before a human ever sees it.</li>" +
            "<li><strong>Live DAG via <code>forge.watch(executionId)</code></strong> — the SDK's new SSE-based method streams a full <code>DagSnapshot</code> on every node transition. This view is it.</li>" +
            "</ul></div>"
        );

        card.add(eyebrow, h, body);
        return card;
    }

    private Div credsCard() {
        Div card = new Div();
        card.getStyle()
            .set("background", Palette.SURFACE)
            .set("border", "1px solid " + Palette.BORDER)
            .set("border-radius", "14px")
            .set("padding", "1.25rem 1.5rem");

        Span eyebrow = new Span("Under the hood");
        eyebrow.getStyle().set("font-size", "11px").set("text-transform", "uppercase")
            .set("letter-spacing", "0.1em").set("color", Palette.INDIGO).set("font-weight", "600");

        H3 h = new H3("Java 21 · Spring Boot 3 · Vaadin Flow 24 · Abenix SDK");
        h.getStyle().set("color", Palette.TEXT_STRONG).set("margin", "0.25rem 0 0.5rem 0")
            .set("font-size", "16px").set("letter-spacing", "-0.02em");

        Html body = new Html(
            "<p style=\"color:#3f3b60;font-size:13px;line-height:1.55;margin:0;\">" +
            "Single JVM process serves the UI at <code>/</code> and the REST API at " +
            "<code>/api/claimsiq/*</code>. All reasoning delegates to Abenix pipelines " +
            "via the bundled <code>abenix-sdk-java</code> module (stdlib-only public surface, " +
            "consumable from Kotlin + Scala with zero glue). The Abenix credential lives " +
            "server-side only — it never reaches the browser." +
            "</p>"
        );

        card.add(eyebrow, h, body);
        return card;
    }
}
