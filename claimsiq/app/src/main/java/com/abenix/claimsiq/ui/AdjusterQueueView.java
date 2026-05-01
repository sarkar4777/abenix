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
import com.vaadin.flow.component.orderedlayout.HorizontalLayout;
import com.vaadin.flow.component.orderedlayout.VerticalLayout;
import com.vaadin.flow.router.PageTitle;
import com.vaadin.flow.router.Route;
import com.vaadin.flow.router.RouteParam;
import com.vaadin.flow.router.RouteParameters;

import java.time.Duration;
import java.time.Instant;
import java.util.List;

/**
 * Adjuster work queue. Lists every claim the AI routed for human
 * review — clearest possible signal that "the AI didn't decide; you
 * do." Click any row to land on {@link AdjusterReviewView} where the
 * adjuster can approve / partial / deny with notes.
 */
@Route(value = "review", layout = MainLayout.class)
@PageTitle("ClaimsIQ · Adjuster queue")
public class AdjusterQueueView extends VerticalLayout {

    public AdjusterQueueView(ClaimsService service) {
        setPadding(true);
        setSpacing(true);
        getStyle().set("max-width", "1200px").set("margin", "0 auto").set("padding", "2rem");

        add(header());
        List<Claim> queue = service.listRoutedToHuman();

        if (queue.isEmpty()) {
            add(emptyCard());
        } else {
            for (Claim c : queue) {
                add(rowCard(c));
            }
        }
    }

    private Div header() {
        Div d = new Div();
        Span eyebrow = new Span("ClaimsIQ · human-in-the-loop");
        eyebrow.getStyle().set("font-size", "11px").set("text-transform", "uppercase")
            .set("letter-spacing", "0.1em").set("color", Palette.AMBER).set("font-weight", "600");
        H1 h = new H1("Adjuster queue");
        h.getStyle().set("color", Palette.TEXT_STRONG).set("margin", "0.25rem 0 0 0")
            .set("font-size", "28px").set("letter-spacing", "-0.025em");
        Span sub = new Span("Claims the pipeline routed for human review. AI decision + reasoning + cited clauses are pre-loaded; you make the final call.");
        sub.getStyle().set("color", Palette.TEXT_BODY).set("font-size", "13.5px").set("display", "block");
        d.add(eyebrow, h, sub);
        return d;
    }

    private Div emptyCard() {
        Div d = new Div();
        d.getStyle()
            .set("background", Palette.SURFACE)
            .set("border", "1px solid " + Palette.BORDER)
            .set("border-radius", "12px")
            .set("padding", "1.5rem 1.75rem")
            .set("text-align", "center")
            .set("color", Palette.TEXT_BODY);
        Span title = new Span("No claims awaiting review.");
        title.getStyle().set("display", "block").set("color", Palette.TEXT_STRONG)
            .set("font-size", "16px").set("font-weight", "600");
        Span sub = new Span("Once the pipeline routes a claim to a human (low confidence, fraud signals, or missing data), it appears here.");
        sub.getStyle().set("font-size", "13px");
        d.add(title, sub);
        return d;
    }

    private Div rowCard(Claim c) {
        Div card = new Div();
        card.getStyle()
            .set("background", Palette.SURFACE)
            .set("border", "1px solid " + Palette.BORDER)
            .set("border-radius", "12px")
            .set("padding", "1.1rem 1.25rem")
            .set("box-shadow", "0 1px 2px rgba(15,23,42,0.04)");

        // Top row: id + claimant + reasoning, plus AI tags
        Span eyebrow = new Span("AI ROUTED · waiting on adjuster");
        eyebrow.getStyle().set("font-size", "10.5px").set("text-transform", "uppercase")
            .set("letter-spacing", "0.1em").set("color", Palette.AMBER).set("font-weight", "600")
            .set("display", "block");

        H2 h = new H2((c.getClaimantName() == null ? "(no name)" : c.getClaimantName())
            + " · " + nullToDash(c.getPolicyNumber()));
        h.getStyle().set("font-size", "16px").set("color", Palette.TEXT_STRONG).set("margin", "0.25rem 0");

        Span filed = new Span("Filed " + (c.getCreatedAt() == null ? "—" :
            humaniseAge(c.getCreatedAt())) + " · id " + c.getId().toString().substring(0, 8));
        filed.getStyle().set("color", Palette.TEXT_SUBTLE).set("font-size", "11.5px");

        // AI's tags
        HorizontalLayout chips = new HorizontalLayout(
            chip("Damage", nullToDash(c.getDamageSeverity()), Palette.VIOLET),
            chip("Fraud", nullToDash(c.getFraudRiskTier()),
                "high".equals(c.getFraudRiskTier()) ? Palette.DENIED : Palette.AMBER),
            chip("Suggested", nullToDash(c.getDecision()), Palette.INDIGO),
            chip("AI cost", c.getCostUsd() == null ? "—" : String.format("$%.4f", c.getCostUsd()),
                Palette.TEXT_MUTED)
        );
        chips.setSpacing(true);
        chips.getStyle().set("flex-wrap", "wrap").set("margin-top", "0.5rem");

        // Adjuster notes preview
        Span notes = new Span(truncate(c.getAdjusterNotes(), 280));
        notes.getStyle().set("display", "block").set("color", Palette.TEXT_BODY).set("font-size", "12.5px")
            .set("line-height", "1.55").set("margin-top", "0.75rem").set("white-space", "pre-wrap");

        Button open = new Button("Review & decide", VaadinIcon.GAVEL.create());
        open.addThemeVariants(ButtonVariant.LUMO_PRIMARY);
        open.getStyle().set("background", Palette.INDIGO).set("color", "white").set("margin-top", "0.85rem");
        open.addClickListener(e -> UI.getCurrent().navigate("review/" + c.getId()));

        card.add(eyebrow, h, filed, chips, notes, open);
        return card;
    }

    static Span chip(String label, String value, String color) {
        Span s = new Span();
        s.getElement().setProperty("innerHTML",
            "<span style=\"color:" + color + "99;font-size:9.5px;text-transform:uppercase;"
            + "letter-spacing:0.1em;margin-right:4px;font-weight:600;\">" + label + "</span>"
            + "<span style=\"color:" + color + ";font-weight:700;\">"
            + (value == null ? "—" : value) + "</span>");
        s.getStyle()
            .set("padding", "3px 9px")
            .set("border-radius", "999px")
            .set("font-size", "11px")
            .set("background", color + "15")
            .set("border", "1px solid " + color + "35");
        return s;
    }

    private String nullToDash(String s) { return s == null || s.isBlank() ? "—" : s; }

    private static String truncate(String s, int n) {
        if (s == null || s.isBlank()) return "(no adjuster notes provided by the pipeline yet)";
        if (s.length() <= n) return s;
        return s.substring(0, n) + "…";
    }

    private static String humaniseAge(Instant when) {
        long mins = Duration.between(when, Instant.now()).toMinutes();
        if (mins < 1) return "moments ago";
        if (mins < 60) return mins + "m ago";
        long hrs = mins / 60;
        if (hrs < 24) return hrs + "h ago";
        return (hrs / 24) + "d ago";
    }
}
