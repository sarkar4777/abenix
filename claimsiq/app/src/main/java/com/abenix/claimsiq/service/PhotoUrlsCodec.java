package com.abenix.claimsiq.service;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;

import java.util.ArrayList;
import java.util.List;

/**
 * Encode/decode the {@code Claim.photoUrls} TEXT column.
 *
 * <p>Historical bug: photo lists were stored as a CSV of
 * {@code data:image/png;base64,iVBOR...} URIs, but data URIs themselves
 * include commas (in their MIME-type/parameter section as well as
 * after the {@code base64,} prefix), so {@code split(",")} produces
 * broken {@code <img src="iVBOR...">} URLs that the browser then
 * fetches as relative paths from the current host (returning 400 +
 * {@code ERR_INVALID_URL}).
 *
 * <p>The new format is a JSON array. {@link #encode(java.util.List)}
 * always writes JSON; {@link #decode(String)} accepts either a JSON
 * array (new) or a legacy CSV string and returns the list of data
 * URIs (or absolute http(s) URLs).
 */
public final class PhotoUrlsCodec {

    private PhotoUrlsCodec() {}

    private static final ObjectMapper JSON = new ObjectMapper();

    /** Cap the serialised payload at 8 MiB. Anything bigger is rejected at FNOL submit time. */
    public static final int MAX_TOTAL_BYTES = 8 * 1024 * 1024;

    public static String encode(List<String> photoUris) {
        if (photoUris == null || photoUris.isEmpty()) return "";
        try {
            return JSON.writeValueAsString(photoUris);
        } catch (Exception e) {
            // Defensive — a Jackson failure on a List<String> is essentially
            // impossible, but if it ever happens we fall through to the
            // newline-joined fallback (also unambiguous against base64).
            return String.join("\n", photoUris);
        }
    }

    public static List<String> decode(String stored) {
        if (stored == null || stored.isBlank()) return List.of();
        String s = stored.trim();
        // Modern format: JSON array.
        if (s.startsWith("[")) {
            try {
                List<String> parsed = JSON.readValue(s, new TypeReference<List<String>>() {});
                return parsed == null ? List.of() : parsed;
            } catch (Exception ignore) {
                // Fall through — likely truncated, try the legacy splits below.
            }
        }
        // Newline-joined fallback (also legal — newlines are illegal inside data URIs).
        if (s.contains("\n")) {
            List<String> out = new ArrayList<>();
            for (String line : s.split("\n")) {
                String t = line.trim();
                if (!t.isEmpty()) out.add(t);
            }
            return out;
        }
        // Legacy CSV: comma-joined data URIs. Split on the well-known
        // {@code ,data:} boundary so commas inside a single data URI
        // (mime parameters / accidental base64 substring matches) don't
        // shatter the URI. The first URI doesn't have a leading
        // {@code ,} so we glue {@code data:} back onto every subsequent
        // chunk.
        List<String> out = new ArrayList<>();
        if (s.contains(",data:")) {
            String[] parts = s.split(",data:");
            for (int i = 0; i < parts.length; i++) {
                String p = parts[i].trim();
                if (p.isEmpty()) continue;
                if (i > 0) p = "data:" + p;
                out.add(p);
            }
        } else if (s.startsWith("data:")) {
            // Single data URI, no commas at the URI boundary level.
            out.add(s);
        } else {
            // Non-data URI input — fall back to a naive comma split.
            for (String chunk : s.split(",")) {
                String t = chunk.trim();
                if (!t.isEmpty()) out.add(t);
            }
        }
        return out;
    }

    /**
     * Best-effort detection of the legacy CSV format — used by the
     * one-shot startup migrator to decide which rows to rewrite.
     */
    public static boolean looksLegacy(String stored) {
        if (stored == null || stored.isBlank()) return false;
        String s = stored.trim();
        if (s.startsWith("[")) return false;        // JSON
        if (s.contains("\n")) return false;         // newline-joined
        return s.contains(",data:") || s.startsWith("data:");
    }
}
