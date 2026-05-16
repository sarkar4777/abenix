package com.abenix.claimsiq.ui;

import com.vaadin.flow.component.html.Div;
import com.vaadin.flow.component.html.H1;
import com.vaadin.flow.component.html.Span;
import com.vaadin.flow.component.icon.VaadinIcon;
import com.vaadin.flow.component.orderedlayout.HorizontalLayout;
import com.vaadin.flow.component.orderedlayout.VerticalLayout;
import com.vaadin.flow.component.sidenav.SideNav;
import com.vaadin.flow.component.sidenav.SideNavItem;
import com.vaadin.flow.router.RouterLayout;

public class MainLayout extends HorizontalLayout implements RouterLayout {

    private final Div content = new Div();

    public MainLayout() {
        setSizeFull();
        setPadding(false);
        setSpacing(false);
        getStyle()
            .set("background", Palette.PAGE_BG)
            .set("color", Palette.TEXT_BODY)
            .set("font-family", "\"Inter\", \"Segoe UI\", system-ui, sans-serif");

        add(buildNav(), buildContent());
    }

    private VerticalLayout buildNav() {
        VerticalLayout nav = new VerticalLayout();
        nav.setWidth("260px");
        nav.getStyle()
            .set("background", Palette.NAV_BG)
            .set("border-right", "1px solid " + Palette.NAV_BORDER)
            .set("min-height", "100vh");
        nav.setPadding(false);
        nav.setSpacing(false);

        // Brand
        HorizontalLayout brand = new HorizontalLayout();
        brand.setAlignItems(Alignment.CENTER);
        brand.setSpacing(true);
        brand.getStyle()
            .set("padding", "1.5rem 1.25rem")
            .set("border-bottom", "1px solid " + Palette.NAV_BORDER);

        Div logo = new Div();
        logo.setText("C");
        logo.getStyle()
            .set("width", "32px").set("height", "32px")
            .set("border-radius", "8px")
            .set("background", "linear-gradient(135deg, " + Palette.INDIGO + ", " + Palette.VIOLET + ")")
            .set("color", "white")
            .set("display", "flex").set("align-items", "center").set("justify-content", "center")
            .set("font-weight", "700").set("font-size", "15px")
            .set("box-shadow", "0 4px 12px " + Palette.INDIGO + "40");

        Div brandCol = new Div();
        H1 title = new H1("ClaimsIQ");
        title.getStyle().set("font-size", "18px").set("margin", "0").set("color", Palette.TEXT_STRONG).set("letter-spacing", "-0.02em");
        Span sub = new Span("Adjudication copilot");
        sub.getStyle().set("font-size", "10px").set("color", Palette.TEXT_SUBTLE)
            .set("text-transform", "uppercase").set("letter-spacing", "0.1em");
        brandCol.add(title, sub);
        brandCol.getStyle().set("display", "flex").set("flex-direction", "column");

        brand.add(logo, brandCol);
        nav.add(brand);

        SideNav side = new SideNav();
        side.getStyle().set("padding", "0.75rem 0.5rem");
        side.addItem(new SideNavItem("Dashboard",      DashboardView.class,     VaadinIcon.DASHBOARD.create()));
        side.addItem(new SideNavItem("New FNOL",       FnolView.class,          VaadinIcon.FILE_ADD.create()));
        side.addItem(new SideNavItem("Claims queue",   ClaimsListView.class,    VaadinIcon.CLIPBOARD_TEXT.create()));
        side.addItem(new SideNavItem("Adjuster queue", AdjusterQueueView.class, VaadinIcon.GAVEL.create()));
        side.addItem(new SideNavItem("Walkthrough",    HelpView.class,          VaadinIcon.LIGHTBULB.create()));
        nav.add(side);

        // Footer
        Div spacer = new Div();
        spacer.getStyle().set("flex", "1");
        nav.add(spacer);

        Div footer = new Div();
        footer.getStyle()
            .set("padding", "1rem 1.25rem")
            .set("border-top", "1px solid " + Palette.NAV_BORDER);
        Span line1 = new Span("Multimodal claim adjudication");
        line1.getStyle().set("font-size", "10px").set("color", Palette.TEXT_SUBTLE)
            .set("text-transform", "uppercase").set("letter-spacing", "0.1em").set("display", "block");
        Span line2 = new Span("Java · Vaadin Flow · Abenix SDK");
        line2.getStyle().set("font-size", "11px").set("color", Palette.TEXT_MUTED)
            .set("margin-top", "0.25rem").set("display", "block");
        footer.add(line1, line2);
        nav.add(footer);

        return nav;
    }

    private Div buildContent() {
        content.setWidthFull();
        content.getStyle().set("min-height", "100vh").set("overflow", "auto");
        return content;
    }

    @Override
    public void showRouterLayoutContent(com.vaadin.flow.component.HasElement content) {
        this.content.removeAll();
        if (content != null) this.content.getElement().appendChild(content.getElement());
    }
}
