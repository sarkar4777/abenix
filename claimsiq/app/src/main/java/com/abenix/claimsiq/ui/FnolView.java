package com.abenix.claimsiq.ui;

import com.abenix.claimsiq.domain.Claim;
import com.abenix.claimsiq.service.ClaimsService;
import com.abenix.claimsiq.service.PhotoUrlsCodec;
import com.abenix.claimsiq.service.SamplePhotos;
import com.vaadin.flow.component.Html;
import com.vaadin.flow.component.UI;
import com.vaadin.flow.component.button.Button;
import com.vaadin.flow.component.button.ButtonVariant;
import com.vaadin.flow.component.html.Anchor;
import com.vaadin.flow.component.html.Div;
import com.vaadin.flow.component.html.H1;
import com.vaadin.flow.component.html.Image;
import com.vaadin.flow.component.html.Span;
import com.vaadin.flow.component.icon.VaadinIcon;
import com.vaadin.flow.component.notification.Notification;
import com.vaadin.flow.component.orderedlayout.HorizontalLayout;
import com.vaadin.flow.component.orderedlayout.VerticalLayout;
import com.vaadin.flow.component.textfield.TextArea;
import com.vaadin.flow.component.textfield.TextField;
import com.vaadin.flow.component.upload.Upload;
import com.vaadin.flow.component.upload.receivers.MultiFileMemoryBuffer;
import com.vaadin.flow.router.PageTitle;
import com.vaadin.flow.router.Route;
import com.vaadin.flow.router.RouteParam;
import com.vaadin.flow.router.RouteParameters;

import java.util.ArrayList;
import java.util.Base64;
import java.util.List;

@Route(value = "fnol", layout = MainLayout.class)
@PageTitle("ClaimsIQ · New FNOL")
public class FnolView extends VerticalLayout {

    private final List<String> photoDataUris = new ArrayList<>();
    private final SamplePhotos samples;
    private Span attachedSummary;

    public FnolView(ClaimsService service, SamplePhotos samples) {
        this.samples = samples;
        setPadding(true);
        setSpacing(true);
        getStyle().set("max-width", "920px").set("margin", "0 auto").set("padding", "2rem");

        add(header());
        add(explainerCard());
        add(formCard(service));
    }

    private Div header() {
        Div d = new Div();
        Span eyebrow = new Span("ClaimsIQ · first notice of loss");
        eyebrow.getStyle().set("font-size", "11px").set("text-transform", "uppercase")
            .set("letter-spacing", "0.1em").set("color", Palette.INDIGO).set("font-weight", "600").set("display", "block");
        H1 h = new H1("File a claim");
        h.getStyle().set("color", Palette.TEXT_STRONG).set("margin", "0.25rem 0 0.25rem 0")
            .set("font-size", "28px").set("letter-spacing", "-0.025em");
        Span sub = new Span("Fill the details below, attach any damage photos, and click submit. "
            + "The pipeline starts the moment the row is saved — you'll land on the claim detail with the live DAG rendering as each agent finishes.");
        sub.getStyle().set("color", Palette.TEXT_BODY).set("font-size", "13.5px").set("line-height", "1.55")
            .set("display", "block").set("max-width", "700px");
        d.add(eyebrow, h, sub);
        return d;
    }

    private Div explainerCard() {
        Div card = new Div();
        card.getStyle()
            .set("background", Palette.INDIGO_SOFT)
            .set("border", "1px solid " + Palette.INDIGO_EDGE)
            .set("border-radius", "12px")
            .set("padding", "1rem 1.25rem");
        Html body = new Html(
            "<p style=\"color:#3f3b60;font-size:12.5px;line-height:1.6;margin:0;\">" +
            "<strong style=\"color:" + Palette.INDIGO + ";\">Tip:</strong> " +
            "The <em>Damage Assessor</em> is multimodal — every attached photo " +
            "gets a structured vision pass (affected components, severity score, " +
            "staged-damage heuristics). If you skip the photos the pipeline still " +
            "runs, just with <code>photo_quality=insufficient</code> and a lower " +
            "Damage Assessor confidence." +
            "</p>"
        );
        card.add(body);
        return card;
    }

    private Div formCard(ClaimsService service) {
        Div card = new Div();
        card.getStyle()
            .set("background", Palette.SURFACE)
            .set("border", "1px solid " + Palette.BORDER)
            .set("border-radius", "12px")
            .set("padding", "1.5rem 1.75rem")
            .set("display", "flex").set("flex-direction", "column").set("gap", "1rem")
            .set("box-shadow", "0 1px 2px rgba(15,23,42,0.04)");

        TextField claimant = new TextField("Claimant name");
        claimant.setWidthFull();
        claimant.setValue("Jane Doe");

        TextField policy = new TextField("Policy number");
        policy.setWidthFull();
        policy.setValue("POL-2024-77321");

        TextField channel = new TextField("Channel");
        channel.setWidthFull();
        channel.setValue("web");

        TextArea desc = new TextArea("Describe the loss");
        desc.setWidthFull();
        desc.setMinHeight("180px");
        desc.setHelperText("Write freely — the FNOL Intake agent classifies claim type, urgency, and PII flags.");
        desc.setValue(
            "Tuesday evening around 6pm I was rear-ended at a stop light on I-5 near exit 168. " +
            "Other driver admitted fault and waited for police. No injuries on either side. " +
            "My rear bumper is crushed inward and the trunk lid won't close — I can see the inner panel is bent. " +
            "I've attached the photos I took at the scene. I need this fixed quickly — it's my only way to work."
        );

        MultiFileMemoryBuffer buffer = new MultiFileMemoryBuffer();
        Upload upload = new Upload(buffer);
        upload.setAcceptedFileTypes("image/jpeg", "image/png", "image/webp");
        upload.setMaxFiles(6);
        upload.setMaxFileSize(10 * 1024 * 1024);
        upload.setDropAllowed(true);
        upload.addSucceededListener(e -> {
            try {
                byte[] bytes = buffer.getInputStream(e.getFileName()).readAllBytes();
                String mime = e.getMIMEType() == null ? "image/jpeg" : e.getMIMEType();
                String dataUri = "data:" + mime + ";base64," + Base64.getEncoder().encodeToString(bytes);
                photoDataUris.add(dataUri);
                updateAttachedSummary();
                Notification.show("Attached " + e.getFileName(), 2000, Notification.Position.BOTTOM_END);
            } catch (Exception ex) {
                Notification.show("Failed to read " + e.getFileName() + ": " + ex.getMessage(),
                    3000, Notification.Position.MIDDLE);
            }
        });

        Button submit = new Button("Submit FNOL + run pipeline", VaadinIcon.PLAY_CIRCLE.create());
        submit.addThemeVariants(ButtonVariant.LUMO_PRIMARY);
        submit.setDisableOnClick(true);
        submit.getStyle().set("background", Palette.INDIGO).set("color", "white")
            .set("box-shadow", "0 4px 14px " + Palette.INDIGO + "40");
        submit.addClickListener(e -> {
            // Encode as JSON instead of CSV — data URIs contain commas
            // inside the base64 payload + MIME-parameter section, so
            // CSV-joining shattered the list on read. JSON is unambiguous.
            String photosJson = PhotoUrlsCodec.encode(photoDataUris);
            if (photosJson.length() > PhotoUrlsCodec.MAX_TOTAL_BYTES) {
                submit.setEnabled(true);
                Notification.show(
                    "Photo payload is too large (" + (photosJson.length() / (1024 * 1024))
                        + " MB). Attach a maximum of 6 images at ~1 MB each.",
                    5000, Notification.Position.MIDDLE);
                return;
            }
            Claim c = service.ingest(new ClaimsService.FnolRequest(
                claimant.getValue(), policy.getValue(),
                channel.getValue(), desc.getValue(), photosJson));
            Notification.show("Claim " + c.getId().toString().substring(0, 8) + " filed — pipeline is running.",
                3000, Notification.Position.BOTTOM_END);
            UI.getCurrent().navigate("claims/" + c.getId());
        });

        card.add(new HorizontalLayout(claimant, policy, channel) {{
            setWidthFull(); setSpacing(true);
            expand(claimant); expand(policy);
        }});
        card.add(desc);
        Span uploadLabel = new Span("Damage photos (optional)");
        uploadLabel.getStyle().set("font-size", "12px").set("color", Palette.TEXT_MUTED).set("font-weight", "600");
        card.add(uploadLabel, upload);

        // Sample-photo strip — gives the multimodal Damage Assessor
        // something to chew on when the user doesn't bring photos.
        // Click thumbnail → adds it to photoDataUris; "use all" sets
        // them in one click. Keeps the demo flow flat.
        attachedSummary = new Span("0 photos attached");
        attachedSummary.getStyle().set("color", Palette.TEXT_MUTED).set("font-size", "11.5px");
        card.add(samplePhotoStrip(), attachedSummary);

        card.add(submit);
        return card;
    }

    private Div samplePhotoStrip() {
        Div wrap = new Div();
        wrap.getStyle()
            .set("background", Palette.SURFACE_SUNKEN)
            .set("border", "1px dashed " + Palette.INDIGO_EDGE)
            .set("border-radius", "10px")
            .set("padding", "0.85rem 1rem");

        Span label = new Span("No photos handy? Try the demo set.");
        label.getStyle().set("display", "block").set("color", Palette.INDIGO)
            .set("font-size", "11px").set("text-transform", "uppercase").set("letter-spacing", "0.1em")
            .set("font-weight", "600");

        Span sub = new Span("Three synthesised damage photos baked into the demo. Click any thumbnail to attach it; the Damage Assessor runs a structured vision pass on each.");
        sub.getStyle().set("display", "block").set("color", Palette.TEXT_BODY).set("font-size", "12px")
            .set("line-height", "1.5").set("margin-top", "0.25rem");

        Div strip = new Div();
        strip.getStyle().set("display", "flex").set("gap", "0.75rem").set("flex-wrap", "wrap")
            .set("margin-top", "0.75rem");

        for (SamplePhotos.SamplePhoto p : samples.all()) {
            Div tile = new Div();
            tile.getStyle()
                .set("flex", "1 1 200px").set("min-width", "180px")
                .set("background", Palette.SURFACE)
                .set("border", "1px solid " + Palette.BORDER)
                .set("border-radius", "10px")
                .set("padding", "0.5rem").set("cursor", "pointer")
                .set("box-shadow", "0 1px 2px rgba(15,23,42,0.04)");
            Image img = new Image(p.dataUri(), p.label());
            img.getStyle().set("width", "100%").set("height", "100px")
                .set("object-fit", "cover").set("border-radius", "6px");
            Span title = new Span(p.label());
            title.getStyle().set("display", "block").set("font-size", "12px").set("font-weight", "600")
                .set("color", Palette.TEXT_STRONG).set("margin-top", "0.4rem");
            Span cap = new Span(p.caption());
            cap.getStyle().set("display", "block").set("font-size", "11px")
                .set("color", Palette.TEXT_BODY).set("line-height", "1.4");
            tile.add(img, title, cap);
            tile.getElement().addEventListener("click", e -> attachSample(p));
            strip.add(tile);
        }

        Button useAll = new Button("Use all 3 sample photos", VaadinIcon.PICTURE.create());
        useAll.addThemeVariants(ButtonVariant.LUMO_TERTIARY);
        useAll.getStyle().set("color", Palette.INDIGO).set("margin-top", "0.75rem");
        useAll.addClickListener(e -> {
            photoDataUris.clear();
            for (SamplePhotos.SamplePhoto p : samples.all()) {
                photoDataUris.add(p.dataUri());
            }
            updateAttachedSummary();
            Notification.show("All 3 sample damage photos attached.", 2000, Notification.Position.BOTTOM_END);
        });

        wrap.add(label, sub, strip, useAll);
        return wrap;
    }

    private void attachSample(SamplePhotos.SamplePhoto p) {
        if (photoDataUris.contains(p.dataUri())) {
            Notification.show("Already attached: " + p.label(), 1500, Notification.Position.BOTTOM_END);
        } else {
            photoDataUris.add(p.dataUri());
            updateAttachedSummary();
            Notification.show("Attached: " + p.label(), 2000, Notification.Position.BOTTOM_END);
        }
    }

    private void updateAttachedSummary() {
        if (attachedSummary == null) return;
        attachedSummary.setText(photoDataUris.size() + " photo" + (photoDataUris.size() == 1 ? "" : "s") + " attached");
    }
}
