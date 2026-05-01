package com.abenix.claimsiq.ui;

import com.abenix.claimsiq.domain.Claim;
import com.abenix.claimsiq.service.ClaimsService;
import com.vaadin.flow.component.UI;
import com.vaadin.flow.component.button.Button;
import com.vaadin.flow.component.button.ButtonVariant;
import com.vaadin.flow.component.html.Div;
import com.vaadin.flow.component.html.H1;
import com.vaadin.flow.component.html.H2;
import com.vaadin.flow.component.html.Span;
import com.vaadin.flow.component.icon.VaadinIcon;
import com.vaadin.flow.component.notification.Notification;
import com.vaadin.flow.component.orderedlayout.HorizontalLayout;
import com.vaadin.flow.component.orderedlayout.VerticalLayout;
import com.vaadin.flow.component.textfield.TextArea;
import com.vaadin.flow.component.textfield.TextField;
import com.vaadin.flow.router.BeforeEnterEvent;
import com.vaadin.flow.router.BeforeEnterObserver;
import com.vaadin.flow.router.PageTitle;
import com.vaadin.flow.router.Route;
import com.vaadin.flow.router.RouteParam;
import com.vaadin.flow.router.RouteParameters;

import java.util.UUID;

@Route(value = "review/:id", layout = MainLayout.class)
@PageTitle("ClaimsIQ · Review claim")
public class AdjusterReviewView extends VerticalLayout implements BeforeEnterObserver {

    private final ClaimsService service;

    public AdjusterReviewView(ClaimsService service) {
        this.service = service;
        setPadding(true);
        setSpacing(true);
        getStyle().set("max-width", "1100px").set("margin", "0 auto").set("padding", "2rem");
    }

    @Override
    public void beforeEnter(BeforeEnterEvent event) {
        removeAll();
        String parameter = event.getRouteParameters().get("id").orElse(null);
        if (parameter == null || parameter.isBlank()) { add(notFound("That id doesn't look right.")); return; }
        UUID id;
        try { id = UUID.fromString(parameter); }
        catch (Exception e) { add(notFound("That id doesn't look right.")); return; }

        Claim c = service.find(id).orElse(null);
        if (c == null) { add(notFound("Claim not found.")); return; }

        Button back = new Button("Back to queue", VaadinIcon.ARROW_LEFT.create());
        back.addThemeVariants(ButtonVariant.LUMO_TERTIARY);
        back.getStyle().set("color", Palette.INDIGO);
        back.addClickListener(e -> UI.getCurrent().navigate(AdjusterQueueView.class));
        add(back);

        // Header
        Span eyebrow = new Span("Review · claim " + c.getId().toString().substring(0, 8));
        eyebrow.getStyle().set("font-size", "11px").set("text-transform", "uppercase")
            .set("letter-spacing", "0.1em").set("color", Palette.AMBER).set("font-weight", "600");
        H1 h = new H1((c.getClaimantName() == null ? "(no name)" : c.getClaimantName())
            + " — adjuster decision required");
        h.getStyle().set("color", Palette.TEXT_STRONG).set("margin", "0.25rem 0 0 0")
            .set("font-size", "26px").set("letter-spacing", "-0.025em");
        Span sub = new Span("The AI flagged this for human review. Read the AI's reasoning, then approve, partially approve, or deny.");
        sub.getStyle().set("color", Palette.TEXT_BODY).set("font-size", "13.5px").set("display", "block");
        add(eyebrow, h, sub);

        // Already reviewed?
        if (c.getReviewerDecision() != null) {
            add(reviewedBanner(c));
        }

        // AI summary
        add(aiSummary(c));

        // Decision form
        add(decisionForm(c));
    }

    private Div reviewedBanner(Claim c) {
        Div d = new Div();
        d.getStyle()
            .set("background", Palette.APPROVED_SOFT)
            .set("border", "1px solid " + Palette.APPROVED + "40")
            .set("border-radius", "12px")
            .set("padding", "1rem 1.25rem")
            .set("color", Palette.APPROVED);
        Span title = new Span("This claim has been reviewed.");
        title.getStyle().set("display", "block").set("font-weight", "700").set("font-size", "14px");
        Span body = new Span(
            "Reviewer: " + (c.getReviewedBy() == null ? "—" : c.getReviewedBy())
            + " · decision: " + c.getReviewerDecision()
            + " · at: " + (c.getReviewedAt() == null ? "—" : c.getReviewedAt().toString())
            + (c.getReviewerNotes() == null || c.getReviewerNotes().isBlank() ?
                "" : "\n\n" + c.getReviewerNotes())
        );
        body.getStyle().set("display", "block").set("white-space", "pre-wrap")
            .set("font-size", "12.5px").set("color", Palette.TEXT_BODY).set("margin-top", "0.4rem");
        d.add(title, body);
        return d;
    }

    private Div aiSummary(Claim c) {
        Div card = new Div();
        card.getStyle()
            .set("background", Palette.SURFACE)
            .set("border", "1px solid " + Palette.BORDER)
            .set("border-radius", "12px")
            .set("padding", "1.25rem 1.5rem");

        H2 h = new H2("AI reasoning summary");
        h.getStyle().set("font-size", "15px").set("color", Palette.TEXT_STRONG).set("margin", "0 0 0.5rem 0");

        // Pills
        HorizontalLayout pills = new HorizontalLayout(
            AdjusterQueueView.chip("Decision", nv(c.getDecision()), Palette.INDIGO),
            AdjusterQueueView.chip("Approved", c.getApprovedAmountUsd() == null ? "—" :
                String.format("$%.0f", c.getApprovedAmountUsd()), Palette.APPROVED),
            AdjusterQueueView.chip("Severity", nv(c.getDamageSeverity()), Palette.VIOLET),
            AdjusterQueueView.chip("Fraud tier", nv(c.getFraudRiskTier()),
                "high".equals(c.getFraudRiskTier()) ? Palette.DENIED : Palette.AMBER),
            AdjusterQueueView.chip("Fraud score", c.getFraudScore() == null ? "—" :
                String.format("%.0f", c.getFraudScore()), Palette.AMBER)
        );
        pills.setSpacing(true);
        pills.getStyle().set("flex-wrap", "wrap").set("margin-bottom", "1rem");

        // Two-col layout: claimant message + adjuster notes
        Div twoCol = new Div();
        twoCol.getStyle()
            .set("display", "grid")
            .set("grid-template-columns", "1fr 1fr")
            .set("gap", "1rem");

        Div claimantBlock = new Div();
        Span lbl = new Span("Claimant message");
        lbl.getStyle().set("display", "block").set("font-size", "10.5px")
            .set("text-transform", "uppercase").set("letter-spacing", "0.1em")
            .set("color", Palette.TEXT_SUBTLE).set("font-weight", "600");
        Span msg = new Span(c.getDescription() == null ? "(empty)" : c.getDescription());
        msg.getStyle().set("display", "block").set("white-space", "pre-wrap")
            .set("color", Palette.TEXT_BODY).set("font-size", "12.5px")
            .set("line-height", "1.55").set("margin-top", "0.4rem");
        claimantBlock.add(lbl, msg);

        Div notesBlock = new Div();
        Span lbl2 = new Span("Pipeline-generated adjuster notes");
        lbl2.getStyle().set("display", "block").set("font-size", "10.5px")
            .set("text-transform", "uppercase").set("letter-spacing", "0.1em")
            .set("color", Palette.TEXT_SUBTLE).set("font-weight", "600");
        Span notes = new Span(c.getAdjusterNotes() == null || c.getAdjusterNotes().isBlank() ?
            "(no adjuster notes available)" : c.getAdjusterNotes());
        notes.getStyle().set("display", "block").set("white-space", "pre-wrap")
            .set("color", Palette.TEXT_BODY).set("font-size", "12.5px")
            .set("line-height", "1.55").set("margin-top", "0.4rem");
        notesBlock.add(lbl2, notes);

        twoCol.add(claimantBlock, notesBlock);

        // Draft letter
        Div letterBlock = new Div();
        letterBlock.getStyle().set("margin-top", "1rem");
        Span lbl3 = new Span("Draft letter to claimant (will be sent if approved)");
        lbl3.getStyle().set("display", "block").set("font-size", "10.5px")
            .set("text-transform", "uppercase").set("letter-spacing", "0.1em")
            .set("color", Palette.TEXT_SUBTLE).set("font-weight", "600");
        Span letter = new Span(c.getDraftLetter() == null || c.getDraftLetter().isBlank() ?
            "(no draft letter)" : c.getDraftLetter());
        letter.getStyle().set("display", "block").set("white-space", "pre-wrap")
            .set("color", Palette.TEXT_BODY).set("font-size", "12.5px")
            .set("line-height", "1.55").set("margin-top", "0.4rem")
            .set("padding", "0.75rem").set("background", Palette.SURFACE_SUNKEN)
            .set("border", "1px solid " + Palette.BORDER).set("border-radius", "8px");
        letterBlock.add(lbl3, letter);

        card.add(h, pills, twoCol, letterBlock);
        return card;
    }

    private Div decisionForm(Claim c) {
        Div card = new Div();
        card.getStyle()
            .set("background", Palette.AMBER_SOFT)
            .set("border", "1px solid " + Palette.AMBER_EDGE)
            .set("border-radius", "12px")
            .set("padding", "1.25rem 1.5rem");

        H2 h = new H2("Your decision");
        h.getStyle().set("font-size", "16px").set("color", Palette.TEXT_STRONG).set("margin", "0 0 0.25rem 0");

        Span sub = new Span("Pick one. Notes are appended to the audit trail and visible on the claim record.");
        sub.getStyle().set("display", "block").set("color", Palette.TEXT_BODY).set("font-size", "12.5px");

        TextField reviewer = new TextField("Your name");
        reviewer.setValue("Adjuster Demo");
        reviewer.setWidthFull();

        TextArea notes = new TextArea("Notes (visible to claimant on appeal)");
        notes.setMinHeight("110px");
        notes.setWidthFull();
        notes.setPlaceholder("e.g. Verified policy active, photos show new damage matching narrative, approving full ACV minus deductible.");

        Button approve = decisionBtn("Approve in full", Palette.APPROVED, () -> submit(c, reviewer.getValue(), "approve", notes.getValue()));
        Button partial = decisionBtn("Approve partially", Palette.AMBER, () -> submit(c, reviewer.getValue(), "partial", notes.getValue()));
        Button deny = decisionBtn("Deny", Palette.DENIED, () -> submit(c, reviewer.getValue(), "deny", notes.getValue()));

        HorizontalLayout actions = new HorizontalLayout(approve, partial, deny);
        actions.setSpacing(true);
        actions.getStyle().set("margin-top", "1rem").set("flex-wrap", "wrap");

        card.add(h, sub, reviewer, notes, actions);
        return card;
    }

    private void submit(Claim c, String reviewer, String decision, String notes) {
        try {
            service.review(c.getId(), reviewer, decision, notes);
            Notification.show("Decision recorded: " + decision, 2500, Notification.Position.BOTTOM_END);
            UI.getCurrent().navigate("claims/" + c.getId());
        } catch (Throwable t) {
            Notification.show("Couldn't save: " + t.getMessage(), 4000, Notification.Position.MIDDLE);
        }
    }

    private Button decisionBtn(String label, String color, Runnable r) {
        Button b = new Button(label);
        b.addThemeVariants(ButtonVariant.LUMO_PRIMARY);
        b.getStyle().set("background", color).set("color", "white")
            .set("box-shadow", "0 3px 10px " + color + "30");
        b.addClickListener(e -> r.run());
        return b;
    }

    private Div notFound(String msg) {
        Div d = new Div();
        d.setText(msg + " Head back to the queue.");
        d.getStyle()
            .set("background", Palette.SURFACE)
            .set("border", "1px solid " + Palette.BORDER)
            .set("border-radius", "10px")
            .set("padding", "1rem")
            .set("color", Palette.TEXT_BODY);
        return d;
    }

    private static String nv(String s) { return s == null || s.isBlank() ? "—" : s; }
}
