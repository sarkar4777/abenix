package com.abenix.claimsiq.ui;

import com.abenix.claimsiq.domain.Claim;
import com.abenix.claimsiq.service.ClaimsService;
import com.vaadin.flow.component.Html;
import com.vaadin.flow.component.UI;
import com.vaadin.flow.component.button.Button;
import com.vaadin.flow.component.button.ButtonVariant;
import com.vaadin.flow.component.html.Div;
import com.vaadin.flow.component.html.H1;
import com.vaadin.flow.component.html.H2;
import com.vaadin.flow.component.html.Image;
import com.vaadin.flow.component.html.Span;
import com.vaadin.flow.component.icon.VaadinIcon;
import com.vaadin.flow.component.orderedlayout.HorizontalLayout;
import com.vaadin.flow.component.orderedlayout.VerticalLayout;
import com.vaadin.flow.router.BeforeEnterEvent;
import com.vaadin.flow.router.BeforeEnterObserver;
import com.vaadin.flow.router.PageTitle;
import com.vaadin.flow.router.Route;

import java.time.Duration;
import java.util.Optional;
import java.util.UUID;

@Route(value = "claims/:id", layout = MainLayout.class)
@PageTitle("ClaimsIQ · Claim detail")
public class ClaimDetailView extends VerticalLayout implements BeforeEnterObserver {

    private final ClaimsService service;

    public ClaimDetailView(ClaimsService service) {
        this.service = service;
        setPadding(true);
        setSpacing(true);
        getStyle().set("max-width", "1180px").set("margin", "0 auto").set("padding", "2rem");
    }

    @Override
    public void beforeEnter(BeforeEnterEvent event) {
        removeAll();
        String parameter = event.getRouteParameters().get("id").orElse(null);
        if (parameter == null || parameter.isBlank()) { add(notFound()); return; }
        UUID id;
        try { id = UUID.fromString(parameter); }
        catch (Exception e) { add(notFound()); return; }
        Optional<Claim> opt = service.find(id);
        if (opt.isEmpty()) { add(notFound()); return; }

        Claim c = opt.get();

        if ("ingested".equals(c.getStatus()) || "running".equals(c.getStatus())) {
            UI ui = UI.getCurrent();
            if (ui != null) {
                ui.setPollInterval(3000);
                final UUID claimUuid = id;
                ui.addPollListener(ev -> {
                    Claim refreshed = service.find(claimUuid).orElse(null);
                    if (refreshed != null && !refreshed.getStatus().equals(c.getStatus())) {
                        // Status changed — force a redraw so the banner,
                        // pills, and decision details reflect the new state.
                        ev.getSource().getPage().reload();
                    }
                });
            }
        }

        Button back = new Button("Back to queue", VaadinIcon.ARROW_LEFT.create());
        back.addThemeVariants(ButtonVariant.LUMO_TERTIARY);
        back.getStyle().set("color", Palette.INDIGO);
        back.addClickListener(e -> UI.getCurrent().navigate(ClaimsListView.class));
        add(back);

        // Hero status banner — explains in plain English where the
        // claim is, so the user doesn't have to decode pill colours.
        add(statusBanner(c));

        // Photo strip — if the FNOL had photos, show them inline so
        // the demo flow is obviously multimodal.
        if (c.getPhotoUrls() != null && !c.getPhotoUrls().isBlank()) {
            add(photoStrip(c.getPhotoUrls()));
        }

        // Header
        VerticalLayout head = new VerticalLayout();
        head.setPadding(false);
        head.setSpacing(false);
        Span eyebrow = new Span("ClaimsIQ · claim " + c.getId().toString().substring(0, 8));
        eyebrow.getStyle().set("font-size", "11px").set("text-transform", "uppercase")
            .set("letter-spacing", "0.1em").set("color", Palette.INDIGO).set("font-weight", "600");
        H1 h = new H1(c.getClaimantName() == null ? "(no name)" : c.getClaimantName());
        h.getStyle().set("color", Palette.TEXT_STRONG).set("margin", "0.25rem 0 0 0")
            .set("font-size", "26px").set("letter-spacing", "-0.025em");
        Span meta = new Span("Policy " + nullToDash(c.getPolicyNumber())
            + " · " + nullToDash(c.getChannel())
            + " · filed " + (c.getCreatedAt() == null ? "—" : c.getCreatedAt().toString()));
        meta.getStyle().set("color", Palette.TEXT_BODY).set("font-size", "12.5px");
        head.add(eyebrow, h, meta);
        add(head);

        // Pills row — hero status indicators
        HorizontalLayout pills = new HorizontalLayout(
            ClaimsListView.statusPill(c.getStatus()),
            pill("Decision", nullToDash(c.getDecision()), Palette.INDIGO),
            pill("Approved", c.getApprovedAmountUsd() == null ? "—" : String.format("$%.0f", c.getApprovedAmountUsd()), Palette.APPROVED),
            pill("Fraud tier", nullToDash(c.getFraudRiskTier()), c.getFraudRiskTier() != null && c.getFraudRiskTier().startsWith("h") ? Palette.DENIED : Palette.AMBER),
            pill("Severity", nullToDash(c.getDamageSeverity()), Palette.VIOLET),
            pill("Cost", c.getCostUsd() == null ? "$0.0000" : String.format("$%.4f", c.getCostUsd()), Palette.VIOLET),
            pill("Duration", c.getDurationMs() == null ? "—"
                : (Duration.ofMillis(c.getDurationMs()).toSeconds() + "s"), Palette.TEXT_MUTED)
        );
        pills.setSpacing(true);
        pills.getStyle().set("flex-wrap", "wrap");
        add(pills);

        // Two-column: message / resolution
        HorizontalLayout two = new HorizontalLayout();
        two.setWidthFull();
        two.setSpacing(true);

        Div msgCard = card();
        H2 msgH = new H2("Claimant message");
        msgH.getStyle().set("font-size", "14px").set("color", Palette.TEXT_STRONG).set("margin", "0");
        Div msgBody = new Div();
        msgBody.setText(c.getDescription() == null ? "(empty)" : c.getDescription());
        msgBody.getStyle()
            .set("color", Palette.TEXT_BODY).set("white-space", "pre-wrap")
            .set("font-size", "13px").set("line-height", "1.55").set("margin-top", "0.5rem");
        msgCard.add(msgH, msgBody);

        Div letterCard = card();
        H2 letterH = new H2("Draft letter to claimant");
        letterH.getStyle().set("font-size", "14px").set("color", Palette.TEXT_STRONG).set("margin", "0");
        Div letterBody = new Div();
        letterBody.setText(c.getDraftLetter() == null
            ? "(pipeline hasn't produced a letter yet — watch the Live DAG below)"
            : c.getDraftLetter());
        letterBody.getStyle()
            .set("color", Palette.TEXT_BODY).set("white-space", "pre-wrap")
            .set("font-size", "13px").set("line-height", "1.55").set("margin-top", "0.5rem");
        letterCard.add(letterH, letterBody);

        two.add(msgCard, letterCard);
        two.setFlexGrow(1, msgCard, letterCard);
        add(two);

        // Adjuster notes + citations
        if (c.getAdjusterNotes() != null || c.getCitationsJson() != null) {
            Div notes = card();
            H2 nh = new H2("Adjuster notes + cited policy clauses");
            nh.getStyle().set("font-size", "14px").set("color", Palette.TEXT_STRONG).set("margin", "0");
            notes.add(nh);
            if (c.getAdjusterNotes() != null) {
                Div n = new Div();
                n.setText(c.getAdjusterNotes());
                n.getStyle().set("color", Palette.TEXT_BODY).set("white-space", "pre-wrap")
                    .set("font-size", "12.5px").set("line-height", "1.55").set("margin-top", "0.5rem");
                notes.add(n);
            }
            if (c.getCitationsJson() != null && !c.getCitationsJson().isBlank()) {
                Html cites = new Html(
                    "<pre style=\"white-space:pre-wrap;word-break:break-word;background:" + Palette.SURFACE_SUNKEN
                    + ";border:1px solid " + Palette.BORDER
                    + ";padding:0.6rem;border-radius:8px;font-size:11.5px;color:" + Palette.TEXT_BODY
                    + ";margin-top:0.5rem;max-height:260px;overflow:auto;\">"
                    + c.getCitationsJson().replace("<", "&lt;") + "</pre>"
                );
                notes.add(cites);
            }
            add(notes);
        }

        // ─── Live DAG view ──────────────────────────────────────────
        Div live = card();
        live.getStyle().set("padding", "0");      // LiveDagView has its own padding
        live.add(new LiveDagView(service.forge(), c.getExecutionId()));
        add(live);

        if ("failed".equals(c.getStatus()) && c.getErrorMessage() != null) {
            Div err = new Div();
            err.setText("Pipeline failed: " + c.getErrorMessage()
                + " — the claim row is preserved; refiling it re-runs the pipeline.");
            err.getStyle()
                .set("background", Palette.FAILED_SOFT)
                .set("border", "1px solid " + Palette.FAILED + "40")
                .set("border-radius", "10px")
                .set("padding", "0.85rem 1rem")
                .set("color", Palette.FAILED)
                .set("font-size", "12.5px");
            add(err);
        }
    }

    private Div card() {
        Div d = new Div();
        d.getStyle()
            .set("flex", "1")
            .set("background", Palette.SURFACE)
            .set("border", "1px solid " + Palette.BORDER)
            .set("border-radius", "12px")
            .set("padding", "1.15rem 1.25rem")
            .set("box-shadow", "0 1px 2px rgba(15,23,42,0.04)");
        return d;
    }

    private Div pill(String label, String value, String color) {
        Div d = new Div();
        d.getStyle()
            .set("background", Palette.SURFACE)
            .set("border", "1px solid " + Palette.BORDER)
            .set("border-radius", "10px")
            .set("padding", "0.5rem 0.75rem")
            .set("box-shadow", "0 1px 2px rgba(15,23,42,0.04)");
        Span l = new Span(label);
        l.getStyle().set("font-size", "9.5px").set("text-transform", "uppercase")
            .set("letter-spacing", "0.1em").set("color", Palette.TEXT_SUBTLE).set("display", "block").set("font-weight", "600");
        Span v = new Span(value);
        v.getStyle().set("color", color).set("font-size", "14px").set("font-weight", "700");
        d.add(l, v);
        return d;
    }

    private Div notFound() {
        Div d = new Div();
        d.setText("Claim not found. The id in the URL may be stale — head back to the queue.");
        d.getStyle()
            .set("background", Palette.SURFACE)
            .set("border", "1px solid " + Palette.BORDER)
            .set("border-radius", "10px")
            .set("padding", "1rem")
            .set("color", Palette.TEXT_BODY);
        return d;
    }

    private String nullToDash(String s) { return s == null || s.isBlank() ? "—" : s; }

    private Div statusBanner(Claim c) {
        Div d = new Div();
        String status = c.getStatus() == null ? "ingested" : c.getStatus();
        String title;
        String body;
        String accent;
        switch (status) {
            case "ingested":
                title = "Claim received — pipeline queued";
                body  = "The FNOL is saved. The pipeline starts as soon as the runtime picks it up; the live DAG below repaints every snapshot.";
                accent = Palette.AMBER;
                break;
            case "running":
                title = "Pipeline is running";
                body  = "Six agents are processing the claim. Watch the live DAG below as each node finishes — usually under 60 seconds total.";
                accent = Palette.INDIGO;
                break;
            case "approved":
                title = "Decision: approved";
                body  = "Pipeline approved this claim against the policy. Approved amount + draft letter sit at the top of this page; coverage citations are in the adjuster notes block.";
                accent = Palette.APPROVED;
                break;
            case "partial":
                title = "Decision: partially approved";
                body  = "The pipeline approved part of the claim — see the approved amount and the draft letter. Coverage exclusions are cited in the notes.";
                accent = Palette.APPROVED;
                break;
            case "denied":
                title = "Decision: denied";
                body  = "The pipeline denied this claim. The denial letter cites the policy clause; an appeal path is in the notes.";
                accent = Palette.DENIED;
                break;
            case "routed_to_human":
                title = "Routed to a human adjuster";
                body  = "The pipeline didn't have enough confidence (low data, fraud signals, or coverage ambiguity). Click the green button to take this into the adjuster review screen.";
                accent = Palette.AMBER;
                break;
            case "failed":
                title = "Pipeline failed — claim row preserved";
                body  = "The pipeline tripped, but the claim row is intact. The error message below is the recoverable reason.";
                accent = Palette.FAILED;
                break;
            default:
                title = "Status: " + status;
                body  = "";
                accent = Palette.TEXT_MUTED;
        }

        d.getStyle()
            .set("background", accent + "12")
            .set("border", "1px solid " + accent + "40")
            .set("border-radius", "12px")
            .set("padding", "1rem 1.25rem");

        Span t = new Span(title);
        t.getStyle().set("display", "block").set("color", accent)
            .set("font-weight", "700").set("font-size", "15px");
        Span b = new Span(body);
        b.getStyle().set("display", "block").set("color", Palette.TEXT_BODY)
            .set("font-size", "12.5px").set("line-height", "1.55").set("margin-top", "0.25rem");

        d.add(t, b);

        if ("routed_to_human".equals(status)) {
            Button cta = new Button("Open adjuster review", VaadinIcon.GAVEL.create());
            cta.addThemeVariants(ButtonVariant.LUMO_PRIMARY);
            cta.getStyle().set("background", Palette.INDIGO).set("color", "white").set("margin-top", "0.75rem");
            cta.addClickListener(e -> UI.getCurrent().navigate("review/" + c.getId()));
            d.add(cta);
        }
        return d;
    }

    private Div photoStrip(String csv) {
        Div wrap = new Div();
        wrap.getStyle()
            .set("background", Palette.SURFACE)
            .set("border", "1px solid " + Palette.BORDER)
            .set("border-radius", "12px")
            .set("padding", "0.85rem 1rem");
        Span lbl = new Span("Damage photos attached to this FNOL");
        lbl.getStyle().set("display", "block").set("font-size", "10.5px")
            .set("text-transform", "uppercase").set("letter-spacing", "0.1em")
            .set("color", Palette.TEXT_SUBTLE).set("font-weight", "600");

        Div strip = new Div();
        strip.getStyle().set("display", "flex").set("gap", "0.5rem")
            .set("flex-wrap", "wrap").set("margin-top", "0.5rem");
        int n = 0;
        for (String uri : csv.split(",")) {
            String u = uri.trim();
            if (u.isEmpty()) continue;
            Image img = new Image(u, "damage photo " + (++n));
            img.getStyle().set("width", "180px").set("height", "120px")
                .set("object-fit", "cover").set("border-radius", "8px")
                .set("border", "1px solid " + Palette.BORDER);
            strip.add(img);
            if (n >= 6) break;
        }
        if (n == 0) return wrap;
        wrap.add(lbl, strip);
        return wrap;
    }
}
