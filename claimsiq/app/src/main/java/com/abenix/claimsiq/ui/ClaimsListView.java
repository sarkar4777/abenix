package com.abenix.claimsiq.ui;

import com.abenix.claimsiq.domain.Claim;
import com.abenix.claimsiq.service.ClaimsService;
import com.vaadin.flow.component.UI;
import com.vaadin.flow.component.button.Button;
import com.vaadin.flow.component.button.ButtonVariant;
import com.vaadin.flow.component.grid.Grid;
import com.vaadin.flow.component.html.Div;
import com.vaadin.flow.component.html.H1;
import com.vaadin.flow.component.html.Span;
import com.vaadin.flow.component.icon.VaadinIcon;
import com.vaadin.flow.component.orderedlayout.HorizontalLayout;
import com.vaadin.flow.component.orderedlayout.VerticalLayout;
import com.vaadin.flow.router.PageTitle;
import com.vaadin.flow.router.Route;
import com.vaadin.flow.router.RouteParam;
import com.vaadin.flow.router.RouteParameters;

import java.time.ZoneId;
import java.time.format.DateTimeFormatter;
import java.util.Map;

@Route(value = "claims", layout = MainLayout.class)
@PageTitle("ClaimsIQ · Claims queue")
public class ClaimsListView extends VerticalLayout {

    private static final Map<String, String[]> STATUS_COLORS = Map.of(
        "approved",        new String[]{Palette.APPROVED, Palette.APPROVED_SOFT},
        "partial",         new String[]{Palette.APPROVED, Palette.APPROVED_SOFT},
        "denied",          new String[]{Palette.DENIED,   Palette.DENIED_SOFT},
        "routed_to_human", new String[]{Palette.ROUTED,   Palette.ROUTED_SOFT},
        "running",         new String[]{Palette.RUNNING,  Palette.RUNNING_SOFT},
        "ingested",        new String[]{Palette.TEXT_MUTED, Palette.SURFACE_SUNKEN},
        "failed",          new String[]{Palette.FAILED,   Palette.FAILED_SOFT}
    );

    public ClaimsListView(ClaimsService service) {
        setPadding(true);
        setSpacing(true);
        getStyle().set("max-width", "1200px").set("margin", "0 auto").set("padding", "2rem");

        add(header());
        Grid<Claim> grid = new Grid<>(Claim.class, false);
        grid.setWidthFull();
        grid.setHeight("68vh");
        grid.getStyle()
            .set("background", Palette.SURFACE)
            .set("border", "1px solid " + Palette.BORDER)
            .set("border-radius", "12px")
            .set("box-shadow", "0 1px 2px rgba(15,23,42,0.04)");

        grid.addColumn(c -> c.getId() == null ? "" : c.getId().toString().substring(0, 8))
            .setHeader("ID").setAutoWidth(true);
        grid.addColumn(Claim::getClaimantName).setHeader("Claimant").setAutoWidth(true);
        grid.addColumn(Claim::getPolicyNumber).setHeader("Policy #").setAutoWidth(true);
        grid.addColumn(Claim::getClaimType).setHeader("Type").setAutoWidth(true);
        grid.addColumn(Claim::getDamageSeverity).setHeader("Severity").setAutoWidth(true);
        grid.addColumn(Claim::getFraudRiskTier).setHeader("Fraud tier").setAutoWidth(true);
        grid.addComponentColumn(c -> statusPill(c.getStatus())).setHeader("Status").setAutoWidth(true);
        grid.addColumn(c -> c.getApprovedAmountUsd() == null ? "—" : String.format("$%.0f", c.getApprovedAmountUsd()))
            .setHeader("Approved").setAutoWidth(true);
        grid.addColumn(c -> c.getCreatedAt() == null ? "" :
            c.getCreatedAt().atZone(ZoneId.systemDefault()).format(DateTimeFormatter.ofPattern("MMM d · HH:mm")))
            .setHeader("Filed").setAutoWidth(true);

        grid.addSelectionListener(e -> e.getFirstSelectedItem().ifPresent(c ->
            UI.getCurrent().navigate("claims/" + c.getId())));

        Runnable reload = () -> grid.setItems(service.listRecent());
        reload.run();

        add(grid);

        Div footnote = new Div();
        footnote.getStyle()
            .set("background", Palette.SURFACE_SUNKEN)
            .set("border", "1px solid " + Palette.BORDER)
            .set("border-radius", "10px")
            .set("padding", "0.85rem 1rem").set("margin-top", "0.5rem")
            .set("color", Palette.TEXT_BODY).set("font-size", "12.5px").set("line-height", "1.55");
        footnote.setText("Click any row to open the claim detail — the decision summary sits at the top; the Live DAG view renders the pipeline as it progresses. Claims stay in the queue even if the pipeline trips: the row lands with status=failed and a recoverable error message instead of taking the app down.");
        add(footnote);
    }

    private HorizontalLayout header() {
        VerticalLayout titleCol = new VerticalLayout();
        titleCol.setPadding(false);
        titleCol.setSpacing(false);
        Span eyebrow = new Span("ClaimsIQ");
        eyebrow.getStyle().set("font-size", "11px").set("text-transform", "uppercase")
            .set("letter-spacing", "0.1em").set("color", Palette.INDIGO).set("font-weight", "600");
        H1 h = new H1("Claims queue");
        h.getStyle().set("color", Palette.TEXT_STRONG).set("margin", "0.25rem 0 0 0")
            .set("font-size", "28px").set("letter-spacing", "-0.025em");
        Span sub = new Span("Every claim filed on this tenant. Decision, fraud tier, and approved amount inline.");
        sub.getStyle().set("color", Palette.TEXT_BODY).set("font-size", "13.5px");
        titleCol.add(eyebrow, h, sub);

        Button fnol = new Button("New FNOL", VaadinIcon.FILE_ADD.create());
        fnol.addThemeVariants(ButtonVariant.LUMO_PRIMARY);
        fnol.getStyle().set("background", Palette.INDIGO).set("color", "white");
        fnol.addClickListener(e -> fnol.getUI().ifPresent(ui -> ui.navigate(FnolView.class)));

        HorizontalLayout row = new HorizontalLayout(titleCol, fnol);
        row.setWidthFull();
        row.setAlignItems(Alignment.CENTER);
        row.expand(titleCol);
        return row;
    }

    static Span statusPill(String status) {
        String[] colors = STATUS_COLORS.getOrDefault(status, new String[]{Palette.TEXT_MUTED, Palette.SURFACE_SUNKEN});
        Span s = new Span(status == null ? "—" : status.replace('_', ' '));
        s.getStyle()
            .set("padding", "2px 9px")
            .set("border-radius", "999px")
            .set("font-size", "11px")
            .set("font-weight", "600")
            .set("text-transform", "lowercase")
            .set("background", colors[1])
            .set("color", colors[0])
            .set("border", "1px solid " + colors[0] + "40");
        return s;
    }
}
