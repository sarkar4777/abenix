package com.abenix.claimsiq.service;

import org.springframework.stereotype.Component;

import javax.imageio.ImageIO;
import java.awt.Color;
import java.awt.Font;
import java.awt.Graphics2D;
import java.awt.RenderingHints;
import java.awt.geom.GeneralPath;
import java.awt.image.BufferedImage;
import java.io.ByteArrayOutputStream;
import java.util.Base64;
import java.util.List;

@Component
public class SamplePhotos {

    public record SamplePhoto(String label, String caption, String dataUri) {}

    private final List<SamplePhoto> photos;

    public SamplePhotos() {
        this.photos = List.of(
            bake("rear-bumper.png",
                "Rear bumper damage",
                "Rear-end collision impact, bumper crushed inward, paint cracked.",
                new Color(0xB45309), new Color(0xFEF3C7),
                g -> drawCar(g, 0.40, true)),
            bake("trunk-lid.png",
                "Trunk lid misaligned",
                "Trunk no longer seats; latch alignment shifted ~2cm right of original.",
                new Color(0xB91C1C), new Color(0xFEE2E2),
                g -> drawCar(g, 0.55, true)),
            bake("inner-panel.png",
                "Inner quarter panel deformation",
                "Visible from the trunk well; structural impact behind the bumper cover.",
                new Color(0x7C3AED), new Color(0xEDE9FE),
                g -> drawCar(g, 0.65, false))
        );
    }

    public List<SamplePhoto> all() { return photos; }

    /** Convenience — comma-joined data URIs in the same shape FnolView already
     *  sends to the pipeline (a CSV of data: URIs). */
    public String asCsv() {
        StringBuilder sb = new StringBuilder();
        for (int i = 0; i < photos.size(); i++) {
            if (i > 0) sb.append(",");
            sb.append(photos.get(i).dataUri());
        }
        return sb.toString();
    }

    private static SamplePhoto bake(String name, String label, String caption,
                                    Color accent, Color bg, java.util.function.Consumer<Graphics2D> drawCar) {
        int W = 720, H = 480;
        BufferedImage img = new BufferedImage(W, H, BufferedImage.TYPE_INT_RGB);
        Graphics2D g = img.createGraphics();
        g.setRenderingHint(RenderingHints.KEY_ANTIALIASING, RenderingHints.VALUE_ANTIALIAS_ON);
        g.setRenderingHint(RenderingHints.KEY_TEXT_ANTIALIASING, RenderingHints.VALUE_TEXT_ANTIALIAS_ON);

        // Background — subtle gradient
        g.setColor(bg);
        g.fillRect(0, 0, W, H);
        g.setColor(new Color(255, 255, 255, 130));
        g.fillRect(0, 0, W, 90);

        // Car silhouette + damage marker
        drawCar.accept(g);

        // Label band
        g.setColor(new Color(15, 23, 42, 220));
        g.fillRoundRect(24, 24, W - 48, 56, 12, 12);
        g.setColor(Color.WHITE);
        g.setFont(new Font(Font.SANS_SERIF, Font.BOLD, 22));
        g.drawString(label, 44, 60);

        g.setColor(new Color(0xCBD5E1));
        g.setFont(new Font(Font.SANS_SERIF, Font.PLAIN, 12));
        g.drawString("ClaimsIQ sample · " + name, W - 230, 72);

        // Caption strip
        g.setColor(new Color(15, 23, 42));
        g.fillRect(0, H - 60, W, 60);
        g.setColor(Color.WHITE);
        g.setFont(new Font(Font.SANS_SERIF, Font.PLAIN, 14));
        g.drawString(caption, 28, H - 24);

        // Damage tag
        g.setColor(accent);
        g.fillRoundRect(W - 200, H - 50, 172, 32, 10, 10);
        g.setColor(Color.WHITE);
        g.setFont(new Font(Font.SANS_SERIF, Font.BOLD, 11));
        g.drawString("DAMAGE EVIDENCE", W - 184, H - 30);

        g.dispose();

        try {
            ByteArrayOutputStream out = new ByteArrayOutputStream();
            ImageIO.write(img, "png", out);
            String b64 = Base64.getEncoder().encodeToString(out.toByteArray());
            return new SamplePhoto(label, caption, "data:image/png;base64," + b64);
        } catch (Exception e) {
            throw new IllegalStateException("Failed to bake sample photo " + name, e);
        }
    }

    private static void drawCar(Graphics2D g, double xFraction, boolean fromBehind) {
        int W = 720, H = 480;
        int cx = W / 2, cy = H / 2 + 20;
        int bodyW = 460, bodyH = 110;

        // Shadow
        g.setColor(new Color(0, 0, 0, 35));
        g.fillOval(cx - bodyW / 2 - 10, cy + bodyH / 2 + 8, bodyW + 20, 24);

        // Body
        g.setColor(new Color(0x4338CA));
        g.fillRoundRect(cx - bodyW / 2, cy - bodyH / 2, bodyW, bodyH, 32, 32);

        // Greenhouse (windows)
        GeneralPath gh = new GeneralPath();
        gh.moveTo(cx - bodyW / 2 + 70, cy - bodyH / 2);
        gh.lineTo(cx - bodyW / 2 + 110, cy - bodyH / 2 - 60);
        gh.lineTo(cx + bodyW / 2 - 110, cy - bodyH / 2 - 60);
        gh.lineTo(cx + bodyW / 2 - 70, cy - bodyH / 2);
        gh.closePath();
        g.setColor(new Color(0x312E81));
        g.fill(gh);

        // Windshield reflection
        g.setColor(new Color(255, 255, 255, 60));
        gh = new GeneralPath();
        gh.moveTo(cx - bodyW / 2 + 75, cy - bodyH / 2 - 5);
        gh.lineTo(cx - bodyW / 2 + 115, cy - bodyH / 2 - 55);
        gh.lineTo(cx - bodyW / 2 + 200, cy - bodyH / 2 - 55);
        gh.lineTo(cx - bodyW / 2 + 160, cy - bodyH / 2 - 5);
        gh.closePath();
        g.fill(gh);

        // Wheels
        g.setColor(new Color(0x1E1B4B));
        g.fillOval(cx - bodyW / 2 + 50, cy + bodyH / 2 - 24, 60, 60);
        g.fillOval(cx + bodyW / 2 - 110, cy + bodyH / 2 - 24, 60, 60);
        g.setColor(new Color(0x6366F1));
        g.fillOval(cx - bodyW / 2 + 70, cy + bodyH / 2 - 4, 20, 20);
        g.fillOval(cx + bodyW / 2 - 90, cy + bodyH / 2 - 4, 20, 20);

        // Damage marker — concentric rings
        int dx = (int) (cx - bodyW / 2 + bodyW * xFraction);
        int dy = cy + (fromBehind ? -10 : 5);
        for (int r = 60, alpha = 30; r > 12; r -= 12, alpha += 30) {
            g.setColor(new Color(220, 38, 38, alpha));
            g.fillOval(dx - r, dy - r, r * 2, r * 2);
        }

        // Crack lines
        g.setColor(new Color(127, 29, 29));
        g.setStroke(new java.awt.BasicStroke(3));
        g.drawLine(dx - 18, dy - 22, dx + 6, dy + 4);
        g.drawLine(dx + 6, dy + 4, dx - 8, dy + 26);
        g.drawLine(dx + 6, dy + 4, dx + 30, dy - 6);
        g.drawLine(dx - 14, dy + 12, dx + 22, dy + 22);

        // "X" exclamation
        g.setColor(new Color(220, 38, 38));
        g.fillOval(dx - 18, dy - 80, 36, 36);
        g.setColor(Color.WHITE);
        g.setFont(new Font(Font.SANS_SERIF, Font.BOLD, 22));
        g.drawString("!", dx - 5, dy - 56);
    }
}
