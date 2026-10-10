import com.abenix.sdk.Abenix;
import com.abenix.sdk.AbenixException;
import com.abenix.sdk.ActionDecision;
import com.abenix.sdk.ActionsClient;
import com.abenix.sdk.Approval;
import com.abenix.sdk.DagSnapshot;
import com.abenix.sdk.ExecutionResult;
import com.abenix.sdk.ExecutionsClient;
import com.abenix.sdk.WatchStream;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.TimeUnit;

/**
 * Java SDK against the live API. Run by scripts/sdk-e2e.sh inside a JDK 21
 * container:  java -cp "sdk.jar:deps/*" LiveSmoke.java
 * Reads ABENIX_URL and the key from ABENIX_API_KEY or SDK_KEY_FILE.
 */
public class LiveSmoke {

    static final String SLUG = System.getenv().getOrDefault("SDK_E2E_AGENT", "sdk-e2e-assistant");
    static final String RUN = UUID.randomUUID().toString().substring(0, 8);
    static final List<String> failures = new ArrayList<>();
    static int passed = 0;

    interface Check { void run() throws Exception; }

    static void check(String name, Check c) {
        try {
            c.run();
            passed++;
            System.out.println("ok   " + name);
        } catch (Throwable t) {
            failures.add(name);
            System.out.println("FAIL " + name + ": " + t);
        }
    }

    static void expect(boolean ok, String what) {
        if (!ok) throw new AssertionError(what);
    }

    public static void main(String[] args) throws Exception {
        String base = System.getenv().getOrDefault("ABENIX_URL", "http://localhost:8000");
        String key = System.getenv("ABENIX_API_KEY");
        if (key == null || key.isBlank()) {
            key = Files.readString(Path.of(System.getenv().getOrDefault("SDK_KEY_FILE", "e2e/sdk/.sdk-key"))).strip();
        }
        Abenix forge = Abenix.builder().baseUrl(base).apiKey(key).build();

        check("identity", () -> {
            Map<?, ?> user = (Map<?, ?>) forge.me().get("user");
            expect(user.get("email") != null, "me has an email");
            expect(!((List<?>) forge.permissions().get("capabilities")).isEmpty(), "capabilities");
        });

        String[] agentId = new String[1];
        check("agent by slug", () -> {
            Map<String, Object> a = forge.agents().bySlug(SLUG);
            if (a == null) {
                a = forge.agents().create(Map.of(
                    "name", "SDK e2e assistant",
                    "slug", SLUG,
                    "description", "Answers short questions. Used by the SDK end to end suites.",
                    "system_prompt", "You answer in one short sentence. No preamble.",
                    "model_config", Map.of("model", "claude-haiku-4-5-20251001", "temperature", 0,
                        "max_tokens", 200, "tools", List.of())));
            }
            agentId[0] = (String) a.get("id");
            expect(forge.agents().bySlug("no-such-agent-" + RUN) == null, "unknown slug is null");
        });

        String[] runId = new String[1];
        check("run and read back", () -> {
            ExecutionResult r = forge.execute(SLUG, "What is the capital of Spain? One word.");
            expect("completed".equals(r.status()), "status " + r.status());
            expect(String.valueOf(r.output()).toLowerCase().contains("madrid"), "output " + r.output());
            runId[0] = r.executionId();
            ExecutionResult back = forge.getExecution(r.executionId());
            expect("completed".equals(back.status()), "read back " + back.status());
            List<Map<String, Object>> rows = forge.executions().list(
                ExecutionsClient.ListOptions.empty().agentId(agentId[0]).triggerKind("api").limit(20));
            expect(rows.stream().anyMatch(x -> r.executionId().equals(x.get("id"))), "listed by agent and trigger");
        });

        check("stream the live DAG of a run", () -> {
            ExecutionResult r = forge.execute(SLUG, "Name a primary colour. One word.",
                Abenix.ExecuteOptions.defaults().waitMode(com.abenix.sdk.WaitMode.SUBMITTED));
            expect(r.executionId() != null, "submitted has an id");
            try (WatchStream w = forge.watch(r.executionId())) {
                DagSnapshot last = w.terminal().get(180, TimeUnit.SECONDS);
                expect(last.isTerminal() && "completed".equals(last.status()), "terminal " + last.status());
            }
        });

        check("approvals", () -> {
            String token = "sdk-java-e2e-" + RUN;
            Approval a = forge.approvals().create("SDK Java e2e: renew the licence", Map.of("seats", 12), 1, 600, null, token);
            expect("pending".equals(a.status()), "pending");
            expect(a.id().equals(forge.approvals().create("dup", Map.of(), 1, 600, null, token).id()), "client token dedupes");
            CompletableFuture<Approval> waited = CompletableFuture.supplyAsync(() -> forge.approvals().waitFor(a.id(), 30));
            Thread.sleep(2000);
            expect("approved".equals(forge.approvals().approve(a.id(), "budgeted").status()), "approve");
            expect("approved".equals(waited.get(40, TimeUnit.SECONDS).status()), "waitFor saw it");
            Approval b = forge.approvals().create("SDK Java e2e: drop the table", Map.of(), 1, 600, null, null);
            expect("denied".equals(forge.approvals().deny(b.id(), "no").status()), "deny");
        });

        check("autonomy propose, wait and outcome", () -> {
            ActionDecision d = forge.actions().propose(ActionsClient.ProposeRequest.of("sample_plant.set_setpoint")
                .arguments(Map.of("operation", "set_setpoint", "setpoint_bar", 4.5))
                .intent("hold 4.5 bar")
                .prediction(Map.of("metric", "pressure_bar", "value", 4.5, "low", 4.45, "high", 4.55)));
            if (d.isWaiting()) {
                CompletableFuture<ActionDecision> w = CompletableFuture.supplyAsync(() -> forge.actions().waitFor(d.actionId(), 30));
                Thread.sleep(2000);
                forge.approvals().approve(d.approvalId(), "ok", Map.of("setpoint_bar", 4.4));
                ActionDecision cleared = w.get(40, TimeUnit.SECONDS);
                expect(cleared.shouldRun(), "cleared " + cleared.decision());
                expect(cleared.edited(), "edited arguments come back");
            } else {
                expect(d.shouldRun(), "decision " + d.decision());
            }
            forge.actions().executed(d.actionId(), true, "applied");
            forge.actions().reportOutcome(d.actionId(), 4.42, "gauge");
            @SuppressWarnings("unchecked")
            Map<String, Object> detail = forge.actions().get(d.actionId());
            Object action = detail.getOrDefault("action", detail);
            expect("executed".equals(((Map<?, ?>) action).get("status")), "executed");
            try {
                forge.actions().propose("no.such.action", Map.of());
                throw new AssertionError("unknown action was accepted");
            } catch (AbenixException e) {
                expect(e.status() == 404 && "UNKNOWN_ACTION".equals(e.code()), "status " + e.status() + " code " + e.code());
            }
        });

        check("lessons and feedback", () -> {
            Map<String, Object> lesson = forge.lessons().report(agentId[0], "Gave a sentence, wanted one word", "Madrid", runId[0]);
            expect(lesson.get("lesson_id") != null, "lesson id");
            Map<String, Object> down = forge.feedback().give(-1, runId[0], null, "Madrid");
            expect(down.get("lesson_id") != null, "thumbs down with a correction is a lesson");
            expect(forge.feedback().give(1, runId[0], null, null).get("id") != null, "thumbs up");
        });

        check("knowledge upload and search", () -> {
            Map<String, Object> boot = forge.knowledge().bootstrapProject("sdk-e2e", "SDK e2e", "",
                List.of(Map.of("name", "SDK e2e notes", "slug", "sdk-e2e-notes")));
            String kb = (String) ((Map<?, ?>) ((List<?>) boot.get("collections")).get(0)).get("id");
            Map<String, Object> doc = forge.knowledge().upload(kb,
                ("Gate " + RUN + " closes at noon on Saturdays.").getBytes(StandardCharsets.UTF_8),
                "gate-" + RUN + ".txt", "text/plain");
            String status = String.valueOf(doc.get("status"));
            for (int i = 0; i < 60 && !List.of("ready", "failed", "degraded").contains(status); i++) {
                Thread.sleep(3000);
                status = forge.knowledge().documents(kb).stream()
                    .filter(x -> doc.get("id").equals(x.get("id"))).map(x -> String.valueOf(x.get("status")))
                    .findFirst().orElse("missing");
            }
            expect("ready".equals(status), "document " + status);
            Map<String, Object> found = forge.knowledge().search(kb, "When does gate " + RUN + " close?", "vector", 5, 0);
            expect(String.valueOf(found.get("results")).contains(RUN), "search found it: " + found);
        });

        System.out.println(passed + " passed, " + failures.size() + " failed");
        System.exit(failures.isEmpty() ? 0 : 1);
    }
}
