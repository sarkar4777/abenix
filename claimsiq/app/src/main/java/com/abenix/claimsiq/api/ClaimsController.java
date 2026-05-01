package com.abenix.claimsiq.api;

import com.abenix.claimsiq.domain.Claim;
import com.abenix.claimsiq.service.ClaimsService;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;
import java.util.Map;
import java.util.UUID;

/**
 * REST surface: list + detail + FNOL ingest. The live-DAG stream is
 * a separate controller so the SSE machinery stays isolated.
 */
@RestController
@RequestMapping(value = "/api/claimsiq", produces = MediaType.APPLICATION_JSON_VALUE)
public class ClaimsController {

    private final ClaimsService service;

    public ClaimsController(ClaimsService service) { this.service = service; }

    @GetMapping("/health")
    public Map<String, Object> health() {
        return Map.of("status", "ok", "service", "claimsiq");
    }

    @GetMapping("/claims")
    public Map<String, Object> list() {
        List<Claim> claims = service.listRecent();
        return Map.of("data", claims, "meta", Map.of("total", claims.size()));
    }

    @GetMapping("/claims/{id}")
    public ResponseEntity<Map<String, Object>> detail(@PathVariable UUID id) {
        return service.find(id)
            .<ResponseEntity<Map<String, Object>>>map(c ->
                ResponseEntity.ok(Map.of("data", c)))
            .orElseGet(() ->
                ResponseEntity.status(HttpStatus.NOT_FOUND).body(Map.of("error", "claim not found")));
    }

    @PostMapping(value = "/claims", consumes = MediaType.APPLICATION_JSON_VALUE)
    public ResponseEntity<Map<String, Object>> ingest(@RequestBody ClaimsService.FnolRequest req) {
        if (req == null || req.description() == null || req.description().isBlank()) {
            return ResponseEntity.badRequest().body(Map.of("error", "description is required"));
        }
        Claim c = service.ingest(req);
        return ResponseEntity
            .status(HttpStatus.ACCEPTED)
            .body(Map.of("data", c));
    }

    @PostMapping(value = "/claims/{id}/review", consumes = MediaType.APPLICATION_JSON_VALUE)
    public ResponseEntity<Map<String, Object>> review(@PathVariable UUID id, @RequestBody Map<String, Object> body) {
        String reviewer = (String) body.getOrDefault("reviewer", "adjuster");
        String decision = (String) body.getOrDefault("decision", "");
        String notes = (String) body.getOrDefault("notes", "");
        try {
            return service.review(id, reviewer, decision, notes)
                .<ResponseEntity<Map<String, Object>>>map(c -> ResponseEntity.ok(Map.of("data", c)))
                .orElseGet(() -> ResponseEntity.status(HttpStatus.NOT_FOUND).body(Map.of("error", "claim not found")));
        } catch (IllegalArgumentException e) {
            return ResponseEntity.badRequest().body(Map.of("error", e.getMessage()));
        }
    }
}
