package com.abenix.claimsiq.service;

import com.abenix.claimsiq.domain.Claim;
import com.abenix.claimsiq.domain.ClaimRepository;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.CommandLineRunner;
import org.springframework.core.annotation.Order;
import org.springframework.stereotype.Component;

import java.time.Instant;
import java.util.List;

/**
 * One-shot startup migrator that rewrites {@code Claim.photoUrls} rows
 * from the legacy CSV format ({@code data:image/png;base64,iVBOR..,data:image/...})
 * into the new JSON-array format. Idempotent — once a row is rewritten,
 * {@link PhotoUrlsCodec#looksLegacy} returns {@code false} and we skip
 * it on subsequent boots.
 */
@Component
@Order(50)
public class PhotoUrlsMigrator implements CommandLineRunner {

    private static final Logger log = LoggerFactory.getLogger(PhotoUrlsMigrator.class);

    private final ClaimRepository repo;

    public PhotoUrlsMigrator(ClaimRepository repo) {
        this.repo = repo;
    }

    @Override
    public void run(String... args) {
        try {
            List<Claim> rows = repo.findAll();
            int rewritten = 0;
            for (Claim c : rows) {
                String stored = c.getPhotoUrls();
                if (!PhotoUrlsCodec.looksLegacy(stored)) continue;
                List<String> uris = PhotoUrlsCodec.decode(stored);
                String json = PhotoUrlsCodec.encode(uris);
                if (json.equals(stored)) continue;     // no-op safety
                c.setPhotoUrls(json);
                c.setUpdatedAt(Instant.now());
                repo.save(c);
                rewritten++;
            }
            if (rewritten > 0) {
                log.info("PhotoUrlsMigrator: rewrote {} legacy CSV photo lists into JSON array format.", rewritten);
            } else {
                log.debug("PhotoUrlsMigrator: nothing to migrate.");
            }
        } catch (Throwable t) {
            // Migration failure must NEVER prevent the app from starting —
            // the renderer is already backwards-compatible with the legacy
            // format, so this is a best-effort cleanup.
            log.warn("PhotoUrlsMigrator failed (non-fatal): {}", t.getMessage());
        }
    }
}
