package com.abenix.claimsiq.ui;

import com.vaadin.flow.component.Html;
import com.vaadin.flow.component.UI;
import com.vaadin.flow.component.button.Button;
import com.vaadin.flow.component.button.ButtonVariant;
import com.vaadin.flow.component.html.Div;
import com.vaadin.flow.component.html.H1;
import com.vaadin.flow.component.html.H2;
import com.vaadin.flow.component.html.Span;
import com.vaadin.flow.component.icon.VaadinIcon;
import com.vaadin.flow.component.orderedlayout.HorizontalLayout;
import com.vaadin.flow.component.orderedlayout.VerticalLayout;
import com.vaadin.flow.router.PageTitle;
import com.vaadin.flow.router.Route;

@Route(value = "help", layout = MainLayout.class)
@PageTitle("ClaimsIQ · Walkthrough")
public class HelpView extends VerticalLayout {

    public HelpView() {
        setPadding(true);
        setSpacing(true);
        getStyle().set("max-width", "900px").set("margin", "0 auto").set("padding", "2rem");

        add(hero());
        add(tour());
        add(pipeline());
        add(tools());
        add(sdk());
        add(troubleshooting());
    }

    private Div hero() {
        Div d = new Div();
        Span eyebrow = new Span("ClaimsIQ · walkthrough");
        eyebrow.getStyle().set("font-size", "11px").set("text-transform", "uppercase")
            .set("letter-spacing", "0.1em").set("color", Palette.INDIGO).set("font-weight", "600").set("display", "block");

        H1 h = new H1("What is ClaimsIQ?");
        h.getStyle().set("color", Palette.TEXT_STRONG).set("margin", "0.25rem 0 0.75rem 0")
            .set("font-size", "34px").set("letter-spacing", "-0.025em");

        Html body = new Html(
            "<div style=\"color:" + Palette.TEXT_BODY + ";font-size:15px;line-height:1.65;\">" +
            "<p style=\"margin:0;\">A <strong>multimodal insurance claim adjudication copilot</strong>, " +
            "end-to-end in Java. Submit a First Notice of Loss, and ClaimsIQ runs a six-agent pipeline that " +
            "cites policy clauses, grades damage photos, screens for fraud, computes a settlement " +
            "with the deductible + limit applied, and drafts the claimant letter.</p>" +
            "<p style=\"margin-top:0.75rem;\">Everything under the hood is <strong>Spring Boot 3 + Vaadin Flow 24 + " +
            "Java 21</strong>. Every reasoning step delegates to an Abenix pipeline via the bundled " +
            "<code>abenix-sdk-java</code> module — stdlib-only public surface, consumable from Kotlin + Scala " +
            "with zero glue.</p></div>"
        );
        d.add(eyebrow, h, body);
        return d;
    }

    private Div tour() {
        Div card = paperCard(Palette.INDIGO_SOFT, Palette.INDIGO_EDGE);
        Span eyebrow = new Span("Thirty-second tour");
        eyebrow.getStyle().set("font-size", "11px").set("text-transform", "uppercase")
            .set("letter-spacing", "0.1em").set("color", Palette.INDIGO).set("font-weight", "600").set("display", "block");

        H2 h = new H2("Fastest way to understand the product");
        h.getStyle().set("font-size", "22px").set("color", Palette.TEXT_STRONG).set("margin", "0.25rem 0 0.75rem 0").set("letter-spacing", "-0.02em");

        Html body = new Html(
            "<ol style=\"color:" + Palette.TEXT_BODY + ";font-size:14px;line-height:1.8;padding-left:1.25rem;margin:0;\">" +
            "<li>Head to <strong>Dashboard</strong> and click <em>Try it now</em> — we file a realistic rear-end-collision FNOL on your behalf.</li>" +
            "<li>You land on the claim detail. The <strong>Live DAG</strong> block fills in as each of the six agents finishes — expand any node to see its input + output JSON, tool calls, tokens, cost.</li>" +
            "<li>Once the pipeline closes you'll see the final decision (approve / partial / deny / route-to-human), cited policy clauses, fraud risk tier, settlement amount, and a warm claimant letter at the top.</li>" +
            "<li>Or use <strong>New FNOL</strong> from the nav to write your own description and attach damage photos — the multimodal Damage Assessor runs <code>image_analyzer</code> on every image.</li>" +
            "</ol>"
        );

        Button go = new Button("Go to the dashboard", VaadinIcon.DASHBOARD.create());
        go.addThemeVariants(ButtonVariant.LUMO_PRIMARY);
        go.getStyle().set("margin-top", "1rem").set("background", Palette.INDIGO).set("color", "white");
        go.addClickListener(e -> UI.getCurrent().navigate(DashboardView.class));

        card.add(eyebrow, h, body, go);
        return card;
    }

    private Div pipeline() {
        Div card = paperCard(Palette.SURFACE, Palette.BORDER);
        Span eyebrow = new Span("The pipeline, step by step");
        eyebrow.getStyle().set("font-size", "11px").set("text-transform", "uppercase")
            .set("letter-spacing", "0.1em").set("color", Palette.AMBER).set("font-weight", "600").set("display", "block");
        H2 h = new H2("Six agents, one decision");
        h.getStyle().set("font-size", "22px").set("color", Palette.TEXT_STRONG).set("margin", "0.25rem 0 1rem 0");

        Div grid = new Div();
        grid.getStyle()
            .set("display", "grid")
            .set("grid-template-columns", "repeat(auto-fit, minmax(260px, 1fr))")
            .set("gap", "0.85rem");

        grid.add(
            step("1", "FNOL Intake", "Classifies claim type (auto / home / health / marine / travel), PII-redacts SSN / DOB / DL#, sets urgency 1–5.",
                "pii_redactor · text_analyzer · moderation"),
            step("2", "Policy Matcher", "Hybrid search over the policy KB; returns coverage sections, exclusions, deductible, limit. Every judgment cites policy_id@version.",
                "knowledge_search"),
            step("3", "Damage Assessor — multimodal", "Runs image_analyzer on every attached photo. Grades severity 0–100, flags staged-damage inconsistencies, estimates repair cost range.",
                "image_analyzer · market_data"),
            step("4", "Fraud Screener", "adverse media + OFAC sanctions + PEP on every named party; pattern heuristics on claim timing + geography + urgency-inflation.",
                "adverse_media · sanctions_screening · pep_screening"),
            step("5", "Valuator", "Deterministic ACV math: gross − depreciation, apply deductible, cap at policy limit. Every numeric step is audited.",
                "financial_calculator · market_data · code_executor"),
            step("6", "Claim Decider", "Final decision (approve / partial / deny / route_to_human) with cited clauses; drafts the claimant letter + adjuster notes; moderation gates the outgoing message.",
                "moderation")
        );

        card.add(eyebrow, h, grid);
        return card;
    }

    private Div step(String n, String title, String body, String tools) {
        Div card = new Div();
        card.getStyle()
            .set("border", "1px solid " + Palette.BORDER)
            .set("border-radius", "10px")
            .set("padding", "0.9rem 1rem")
            .set("background", Palette.PAGE_BG);

        HorizontalLayout top = new HorizontalLayout();
        top.setSpacing(true);
        top.setAlignItems(Alignment.CENTER);
        Div num = new Div();
        num.setText(n);
        num.getStyle()
            .set("width", "26px").set("height", "26px")
            .set("border-radius", "999px")
            .set("background", Palette.INDIGO).set("color", "white")
            .set("display", "flex").set("align-items", "center").set("justify-content", "center")
            .set("font-weight", "700").set("font-size", "12px").set("flex-shrink", "0");
        Span t = new Span(title);
        t.getStyle().set("color", Palette.TEXT_STRONG).set("font-weight", "700").set("font-size", "14.5px");
        top.add(num, t);

        Span b = new Span(body);
        b.getStyle().set("color", Palette.TEXT_BODY).set("font-size", "13px")
            .set("line-height", "1.55").set("display", "block").set("margin-top", "0.55rem");

        Span tl = new Span(tools);
        tl.getStyle().set("color", Palette.TEXT_SUBTLE).set("font-size", "11.5px")
            .set("font-family", "ui-monospace, Menlo, monospace").set("display", "block")
            .set("margin-top", "0.55rem");

        card.add(top, b, tl);
        return card;
    }

    private Div tools() {
        Div card = paperCard(Palette.AMBER_SOFT, Palette.AMBER_EDGE);
        Span eyebrow = new Span("Tools · beyond a single LLM call");
        eyebrow.getStyle().set("font-size", "11px").set("text-transform", "uppercase")
            .set("letter-spacing", "0.1em").set("color", Palette.AMBER).set("font-weight", "600").set("display", "block");

        H2 h = new H2("Why ClaimsIQ is a multi-tool workload");
        h.getStyle().set("font-size", "22px").set("color", Palette.TEXT_STRONG).set("margin", "0.25rem 0 0.75rem 0");

        Html body = new Html(
            "<div style=\"color:" + Palette.TEXT_BODY + ";font-size:14px;line-height:1.7;\">" +
            "<p style=\"margin:0;\">You can't adjudicate a claim with prompt engineering alone — the math has to be deterministic, the watchlist hits have to be real, and the vision pass has to see pixels. ClaimsIQ exercises:</p>" +
            "<ul style=\"margin-top:0.75rem;padding-left:1.25rem;\">" +
            "<li><strong>image_analyzer</strong> — multimodal vision on every uploaded damage photo.</li>" +
            "<li><strong>adverse_media · sanctions_screening · pep_screening</strong> — three parallel watchlist hits run on every named party before a dollar moves.</li>" +
            "<li><strong>financial_calculator · code_executor</strong> — deterministic ACV math. Every step is auditable, no hallucinated numbers.</li>" +
            "<li><strong>knowledge_search</strong> — hybrid retrieval over the policy KB. Every coverage argument carries <code>policy_id@version</code>.</li>" +
            "<li><strong>moderation</strong> — post-LLM filter on the outgoing claimant letter before a human sees it.</li>" +
            "</ul></div>"
        );
        card.add(eyebrow, h, body);
        return card;
    }

    private Div sdk() {
        Div card = paperCard(Palette.SURFACE, Palette.BORDER);
        Span eyebrow = new Span("SDK · live DAG");
        eyebrow.getStyle().set("font-size", "11px").set("text-transform", "uppercase")
            .set("letter-spacing", "0.1em").set("color", Palette.VIOLET).set("font-weight", "600").set("display", "block");

        H2 h = new H2("forge.watch(executionId) — a new verb in every language");
        h.getStyle().set("font-size", "22px").set("color", Palette.TEXT_STRONG).set("margin", "0.25rem 0 0.75rem 0");

        Html body = new Html(
            "<div style=\"color:" + Palette.TEXT_BODY + ";font-size:14px;line-height:1.65;\">" +
            "<p style=\"margin:0;\">ClaimsIQ ships an SDK method that any application can use to render a " +
            "live pipeline DAG — the <code>LiveDagView</code> block on the claim detail is a plain Vaadin " +
            "<code>VerticalLayout</code> consuming it. Each snapshot is idempotent: the renderer just " +
            "repaints, no reconciliation logic.</p>" +
            "<pre style=\"background:" + Palette.SURFACE_SUNKEN + ";border:1px solid " + Palette.BORDER +
            ";padding:0.85rem;border-radius:8px;font-size:12.5px;color:" + Palette.TEXT_BODY +
            ";margin-top:0.75rem;overflow:auto;\">try (var stream = forge.watch(executionId)) {\n" +
            "    stream.onSnapshot(snap -&gt; ui.render(snap));\n" +
            "    stream.terminal().join();\n" +
            "}</pre>" +
            "<p style=\"margin-top:0.75rem;\">Same verb shape in Python, TypeScript, Java — the transport " +
            "is plain SSE so there's nothing Kotlin- or Scala-specific to build. A Kotlin consumer just " +
            "writes <code>stream.onSnapshot { ui.render(it) }</code>; Scala is the same with <code>=&gt;</code>.</p>" +
            "<p style=\"margin-top:0.75rem;\">Integrated across every sample app in the repo — ResolveAI, " +
            "the example app, Saudi Tourism, Industrial IoT, and of course ClaimsIQ.</p>" +
            "</div>"
        );
        card.add(eyebrow, h, body);
        return card;
    }

    private Div troubleshooting() {
        Div card = paperCard(Palette.SURFACE_SUNKEN, Palette.BORDER);

        H2 h = new H2("If something breaks");
        h.getStyle().set("font-size", "20px").set("color", Palette.TEXT_STRONG).set("margin", "0 0 0.75rem 0");

        Html body = new Html(
            "<dl style=\"color:" + Palette.TEXT_BODY + ";font-size:13.5px;line-height:1.65;margin:0;\">" +
            "<dt style=\"color:" + Palette.TEXT_STRONG + ";font-weight:700;margin-top:0.5rem;\">A page shows an inline error card.</dt>" +
            "<dd style=\"margin-left:0;margin-top:0.2rem;\">Click Retry — one fetch hiccup during a deploy is the most common cause. The rest of the app stays usable.</dd>" +
            "<dt style=\"color:" + Palette.TEXT_STRONG + ";font-weight:700;margin-top:0.75rem;\">A claim sits in <code>pipeline_error</code>.</dt>" +
            "<dd style=\"margin-left:0;margin-top:0.2rem;\">The Abenix API was unreachable when the pipeline fired. The claim row is preserved; refiling re-runs it on the healthy pod.</dd>" +
            "<dt style=\"color:" + Palette.TEXT_STRONG + ";font-weight:700;margin-top:0.75rem;\">Pipeline takes longer than 45 seconds.</dt>" +
            "<dd style=\"margin-left:0;margin-top:0.2rem;\">Cold LLM paths can take 60–90s on the first run of a fresh pod. Subsequent claims on the same tenant warm up connection pooling and return in ~35s.</dd>" +
            "<dt style=\"color:" + Palette.TEXT_STRONG + ";font-weight:700;margin-top:0.75rem;\">Many users in the demo at once.</dt>" +
            "<dd style=\"margin-left:0;margin-top:0.2rem;\">Claims are tenant-scoped. If you see a 429 in the Live DAG view, the LLM provider rate-limited the batch — refile and it'll pick up on the retry.</dd>" +
            "</dl>"
        );
        card.add(h, body);
        return card;
    }

    private Div paperCard(String bg, String border) {
        Div d = new Div();
        d.getStyle()
            .set("background", bg)
            .set("border", "1px solid " + border)
            .set("border-radius", "14px")
            .set("padding", "1.5rem 1.75rem");
        return d;
    }
}
