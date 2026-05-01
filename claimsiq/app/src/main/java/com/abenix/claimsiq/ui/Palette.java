package com.abenix.claimsiq.ui;

public final class Palette {

    private Palette() {}

    // Backgrounds
    public static final String PAGE_BG        = "#F5F3EE";   // warm off-white paper
    public static final String SURFACE        = "#FFFFFF";   // card bg
    public static final String SURFACE_SUNKEN = "#EFECE4";   // slight grey-cream for sunken elements
    public static final String BORDER         = "#E1DDD3";   // paper border
    public static final String BORDER_STRONG  = "#CDC6B7";

    // Text
    public static final String TEXT_STRONG = "#1E1B4B";       // deep indigo
    public static final String TEXT_BODY   = "#3F3B60";       // muted indigo
    public static final String TEXT_MUTED  = "#6B6682";
    public static final String TEXT_SUBTLE = "#8E8AA3";

    // Primary (indigo) + accent (amber)
    public static final String INDIGO      = "#4338CA";
    public static final String INDIGO_SOFT = "#EEF2FF";
    public static final String INDIGO_EDGE = "#C7D2FE";
    public static final String AMBER       = "#B45309";       // warm brass, not a screaming CTA yellow
    public static final String AMBER_SOFT  = "#FEF3C7";
    public static final String AMBER_EDGE  = "#FCD34D";
    public static final String VIOLET      = "#7C3AED";

    // Status semantics
    public static final String APPROVED = "#047857";          // calm emerald
    public static final String APPROVED_SOFT = "#D1FAE5";
    public static final String DENIED   = "#B91C1C";
    public static final String DENIED_SOFT = "#FEE2E2";
    public static final String ROUTED   = AMBER;
    public static final String ROUTED_SOFT = AMBER_SOFT;
    public static final String RUNNING  = INDIGO;
    public static final String RUNNING_SOFT = INDIGO_SOFT;
    public static final String FAILED   = "#9F1239";
    public static final String FAILED_SOFT = "#FFE4E6";

    // Sidebar
    public static final String NAV_BG     = "#FFFFFF";
    public static final String NAV_BG_SUB = "#F5F3EE";
    public static final String NAV_BORDER = BORDER;
}
