use std::collections::BTreeMap;
use std::collections::hash_map::DefaultHasher;
use std::hash::{Hash, Hasher};
use zellij_tile::prelude::*;

const MIN_STATE_TICK_GAP: u64 = 1;
const HEARTBEAT_FAIL_THRESHOLD: u8 = 3;
const BLOCKED_EXIT_CONFIRM_SAMPLES: u8 = 3;
const WORKING_EXIT_CONFIRM_SAMPLES: u8 = 3;
const UNKNOWN_FALLBACK_CONFIRM_SAMPLES: u8 = 3;
const PLUGIN_VERSION: &str = "1.0.0";
const DEFAULT_WEBHOOK_URL: &str = "http://localhost:18787/webhook/zellij/state_change";
const PROMPT_READY_REAFFIRM_TICKS: u64 = 5;
const PROMPT_READY_REAFFIRM_BUDGET: u8 = 0;
const BOOTSTRAP_SYNC_WINDOW_TICKS: u64 = 15;
const BOOTSTRAP_PROMPT_READY_REAFFIRM_TICKS: u64 = 2;
const BOOTSTRAP_PROMPT_READY_REAFFIRM_BUDGET: u8 = 0;
const BOOTSTRAP_STABLE_REQUIRED: u8 = 3;
const HUMAN_INPUT_CONFIRM_WINDOW_TICKS: u64 = 10;
const HUMAN_INPUT_CONFIRM_COUNT: u8 = 3;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum SemanticState {
    Unknown,
    PromptReady,
    BlockedOnApproval,
    Working,
    CodeAiExited,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum HeartbeatState {
    Ok,
    Fail,
}

impl HeartbeatState {
    fn as_str(self) -> &'static str {
        match self {
            HeartbeatState::Ok => "OK",
            HeartbeatState::Fail => "FAIL",
        }
    }
}

impl SemanticState {
    fn as_str(self) -> &'static str {
        match self {
            SemanticState::Unknown => "UNKNOWN",
            SemanticState::PromptReady => "PROMPT_READY",
            SemanticState::BlockedOnApproval => "BLOCKED_ON_APPROVAL",
            SemanticState::Working => "WORKING",
            SemanticState::CodeAiExited => "CodingAI Exited",
        }
    }
}

struct CodeLeaderVision {
    last_event_type: String,
    last_event_time: String,
    event_count: u32,
    tick_count: u64,

    semantic_state: SemanticState,
    semantic_reason: String,
    semantic_source: String,
    semantic_seq: u64,
    semantic_fingerprint: String,
    last_state_change_tick: u64,
    blocked_exit_pending_samples: u8,
    working_exit_pending_samples: u8,
    unknown_enter_pending_samples: u8,
    heartbeat_state: HeartbeatState,
    probe_fail_streak: u8,

    webhook_url: String,
    session_id: String,
    target_session: String,
    target_tab: String,
    target_pane_role: String,
    webhook_enabled: bool,
    last_webhook_seq: u64,
    last_semantic_webhook_tick: u64,
    prompt_ready_reaffirm_budget: u8,
    bootstrap_sync_until_tick: u64,
    bootstrap_phase: bool,
    bootstrap_stable_count: u8,
    recent_input_received_count: u8,
    recent_input_received_tick: u64,
    last_screen_hash: u64,
}

impl Default for CodeLeaderVision {
    fn default() -> Self {
        Self {
            last_event_type: String::new(),
            last_event_time: String::new(),
            event_count: 0,
            tick_count: 0,
            semantic_state: SemanticState::Unknown,
            semantic_reason: "boot".to_string(),
            semantic_source: "target_probe:CodeLeader/Tab1/CodingAI".to_string(),
            semantic_seq: 0,
            semantic_fingerprint: String::new(),
            last_state_change_tick: 0,
            blocked_exit_pending_samples: 0,
            working_exit_pending_samples: 0,
            unknown_enter_pending_samples: 0,
            heartbeat_state: HeartbeatState::Ok,
            probe_fail_streak: 0,
            last_screen_hash: 0,
            webhook_url: DEFAULT_WEBHOOK_URL.to_string(),
            session_id: "CodeLeader".to_string(),
            target_session: "CodeLeader".to_string(),
            target_tab: "Tab1".to_string(),
            target_pane_role: "CodingAI".to_string(),
            webhook_enabled: true,
            last_webhook_seq: 0,
            last_semantic_webhook_tick: 0,
            prompt_ready_reaffirm_budget: 0,
            bootstrap_sync_until_tick: BOOTSTRAP_SYNC_WINDOW_TICKS,
            bootstrap_phase: true,
            bootstrap_stable_count: 0,
            recent_input_received_count: 0,
            recent_input_received_tick: 0,
        }
    }
}

register_plugin!(CodeLeaderVision);

impl CodeLeaderVision {
    fn json_escape(input: &str) -> String {
        input
            .replace('\\', "\\\\")
            .replace('"', "\\\"")
            .replace('\n', "\\n")
    }

    fn fingerprint_for(state: SemanticState, reason: &str, recent: &str) -> String {
        match state {
            SemanticState::BlockedOnApproval => {
                let mut hasher = DefaultHasher::new();
                state.as_str().hash(&mut hasher);
                reason.hash(&mut hasher);
                recent.hash(&mut hasher);
                format!("{:016x}", hasher.finish())
            }
            _ => format!("{}::{}", state.as_str(), reason),
        }
    }

    fn emit_state_webhook(&mut self, force: bool) {
        if !self.webhook_enabled {
            return;
        }
        if self.semantic_seq == 0 {
            return;
        }
        if !force && self.semantic_seq == self.last_webhook_seq {
            return;
        }

        let payload = format!(
            r#"{{"source":"plugin","session_id":"{}","event_type":"{}","reason":"{}","fingerprint":"{}","seq":{},"tick":{}}}"#,
            Self::json_escape(&self.session_id),
            self.semantic_state.as_str(),
            Self::json_escape(&self.semantic_reason),
            Self::json_escape(&self.semantic_fingerprint),
            self.semantic_seq,
            self.tick_count,
        );

        let cmd: Vec<String> = vec![
            "curl".to_string(),
            "-sS".to_string(),
            "-m".to_string(),
            "2".to_string(),
            "-X".to_string(),
            "POST".to_string(),
            self.webhook_url.clone(),
            "-H".to_string(),
            "Content-Type: application/json".to_string(),
            "-d".to_string(),
            payload,
        ];
        let cmd_refs: Vec<&str> = cmd.iter().map(|s| s.as_str()).collect();
        run_command(&cmd_refs, BTreeMap::new());
        self.last_webhook_seq = self.semantic_seq;
        self.last_semantic_webhook_tick = self.tick_count;
    }

    fn should_emit_human_input(&mut self, is_screen_change: bool) -> bool {
        // During bootstrap, suppress all human input detection to avoid
        // false positives from the initial TUI rendering.
        if self.bootstrap_phase {
            self.recent_input_received_count = 0;
            return false;
        }

        let eligible = matches!(
            self.semantic_state,
            SemanticState::PromptReady | SemanticState::BlockedOnApproval
        );
        if !eligible {
            self.recent_input_received_count = 0;
            return false;
        }

        let tick_gap = self.tick_count.saturating_sub(self.recent_input_received_tick);

        if is_screen_change {
            if tick_gap == 0 && self.recent_input_received_count > 0 {
                // Same tick, multiple events fired (e.g., Timer + ModeUpdate). Don't double count.
            } else if tick_gap <= HUMAN_INPUT_CONFIRM_WINDOW_TICKS {
                self.recent_input_received_count = self.recent_input_received_count.saturating_add(1);
            } else {
                self.recent_input_received_count = 1;
            }
            self.recent_input_received_tick = self.tick_count;
        } else if tick_gap > HUMAN_INPUT_CONFIRM_WINDOW_TICKS {
            // Decay count if no input received within window
            self.recent_input_received_count = 0;
        }

        if self.recent_input_received_count >= HUMAN_INPUT_CONFIRM_COUNT {
            self.recent_input_received_count = 0;
            return true;
        }
        false
    }

    fn emit_human_input_webhook(&self, input_kind: &str) {
        if !self.webhook_enabled {
            return;
        }
        let payload = format!(
            r#"{{"source":"plugin","session_id":"{}","event_type":"HUMAN_INPUT","reason":"human:input_active","input_kind":"{}","tick":{}}}"#,
            Self::json_escape(&self.session_id),
            Self::json_escape(input_kind),
            self.tick_count,
        );

        let cmd: Vec<String> = vec![
            "curl".to_string(),
            "-sS".to_string(),
            "-m".to_string(),
            "2".to_string(),
            "-X".to_string(),
            "POST".to_string(),
            self.webhook_url.clone(),
            "-H".to_string(),
            "Content-Type: application/json".to_string(),
            "-d".to_string(),
            payload,
        ];
        let cmd_refs: Vec<&str> = cmd.iter().map(|s| s.as_str()).collect();
        run_command(&cmd_refs, BTreeMap::new());
    }

    fn maybe_reaffirm_prompt_ready(&mut self) {
        if self.bootstrap_phase {
            return;
        }
        if self.semantic_state != SemanticState::PromptReady {
            return;
        }
        if self.prompt_ready_reaffirm_budget == 0 {
            return;
        }
        let in_bootstrap_window = self.tick_count <= self.bootstrap_sync_until_tick;
        let reaffirm_ticks = if in_bootstrap_window {
            BOOTSTRAP_PROMPT_READY_REAFFIRM_TICKS
        } else {
            PROMPT_READY_REAFFIRM_TICKS
        };
        let tick_gap = self.tick_count.saturating_sub(self.last_semantic_webhook_tick);
        if tick_gap < reaffirm_ticks {
            return;
        }
        self.emit_state_webhook(true);
        self.prompt_ready_reaffirm_budget = self.prompt_ready_reaffirm_budget.saturating_sub(1);
    }

    fn maybe_transition(&mut self, next: SemanticState, reason: String, fingerprint: String) {
        let tick_gap = self.tick_count.saturating_sub(self.last_state_change_tick);
        let changed = next != self.semantic_state
            || reason != self.semantic_reason
            || fingerprint != self.semantic_fingerprint;

        if changed && tick_gap >= MIN_STATE_TICK_GAP {
            let prev_state = self.semantic_state;
            self.semantic_state = next;
            self.semantic_reason = reason;
            self.semantic_fingerprint = fingerprint;
            self.semantic_source = format!(
                "target_probe:{}/{}/{}",
                self.target_session, self.target_tab, self.target_pane_role
            );
            self.semantic_seq += 1;
            self.last_state_change_tick = self.tick_count;
            // Do NOT reset recent_input tracking here;
            // human input detection runs independently of state transitions.
            self.prompt_ready_reaffirm_budget = if prev_state != SemanticState::PromptReady
                && next == SemanticState::PromptReady
            {
                if self.tick_count <= self.bootstrap_sync_until_tick {
                    BOOTSTRAP_PROMPT_READY_REAFFIRM_BUDGET
                } else {
                    PROMPT_READY_REAFFIRM_BUDGET
                }
            } else if next != SemanticState::PromptReady {
                0
            } else {
                self.prompt_ready_reaffirm_budget
            };
            if self.bootstrap_phase {
                self.bootstrap_stable_count = self.bootstrap_stable_count.saturating_add(1);
                if self.bootstrap_stable_count >= BOOTSTRAP_STABLE_REQUIRED {
                    self.bootstrap_phase = false;
                }
            }
            self.emit_state_webhook(false);
        }
    }

    fn classify_claude_tui(&mut self, text: &str) {
        use std::collections::hash_map::DefaultHasher;
        use std::hash::{Hash, Hasher};
        // Check for screen changes to detect human input implicitly.
        // We strip the very last line before hashing to ignore the blinking cursor or elapsed time spinners 
        // that often update every second and cause false-positive screen changes when idle.
        let text_to_hash = match text.rfind('\n') {
            Some(idx) => &text[..idx],
            None => text,
        };

        let mut hasher = DefaultHasher::new();
        text_to_hash.hash(&mut hasher);
        let current_hash = hasher.finish();
        
        let is_screen_change = self.last_screen_hash != 0 && current_hash != self.last_screen_hash;

        if self.should_emit_human_input(is_screen_change) {
            self.emit_human_input_webhook("screen_change");
        }
        
        self.last_screen_hash = current_hash;

        // Claude Code single-tool state machine (MVP+)
        // Priority: BLOCKED > WORKING > READY/UNKNOWN fallback
        // Use latest visible tail + hysteresis to suppress flicker.
        let lines: Vec<&str> = text.lines().collect();
        let n = lines.len();
        let start = n.saturating_sub(10);
        let recent = lines[start..].join("\n");
        let recent_lc = recent.to_lowercase();

        let has_prompt = recent.contains("❯") || recent.contains("Try \"edit <filepath> to...\"");
        let has_ready_shortcuts = recent.contains("? for shortcuts");
        let has_ready_accept_edits = recent.contains("accept edits on");
        let has_ready_plan_mode = recent.contains("plan mode on");
        let has_ready_try_prompt = recent.contains("Try \"");
        let _last_non_empty = lines
            .iter()
            .rev()
            .map(|s| s.trim())
            .find(|s| !s.is_empty())
            .unwrap_or("");
        let codeai_exited_hint = recent.contains("Resume this session with:")
            && recent.contains("claude --resume");

        let has_approval_question = recent.contains("Do you want to ");
        let has_yes_option = recent.contains("1. Yes");
        let has_two_option_no = recent.contains("2. No");
        let has_three_option_no = recent.contains("3. No");
        let has_second_approval_option = recent.contains("2. Yes")
            || recent.contains("Yes, and always allow")
            || recent.contains("Yes, allow all edits during this session");
        let has_two_way_approval_menu = has_yes_option && has_two_option_no;
        let has_three_way_approval_menu = has_yes_option && has_three_option_no && has_second_approval_option;
        let is_blocked = has_approval_question && (has_two_way_approval_menu || has_three_way_approval_menu);

        let blocked_reason = if recent.contains("allow all edits during this session") {
            "claude:approval_prompt_yes_allow_session_no"
        } else if recent.contains("Yes, and always allow") {
            "claude:approval_prompt_yes_always_no"
        } else {
            "claude:approval_prompt_generic_yes_no"
        };
        let blocked_fingerprint = Self::fingerprint_for(
            SemanticState::BlockedOnApproval,
            blocked_reason,
            &recent,
        );

        let has_thinking = recent_lc.contains("(thinking)") || recent_lc.contains("thinking");
        let has_streaming_tokens = recent.contains("tokens)") && recent.contains("· ↓");
        let has_running = recent.contains("Running…") || recent.contains("Running...");
        let has_interrupt = recent.contains("esc to interrupt");

        let is_working = has_thinking || has_streaming_tokens || has_running || has_interrupt;
        let has_ready_affordance = has_ready_shortcuts
            || has_ready_accept_edits
            || has_ready_plan_mode
            || has_ready_try_prompt;
        let is_ready = has_prompt && has_ready_affordance && !is_working && !is_blocked;

        if is_blocked {
            self.blocked_exit_pending_samples = 0;
            self.working_exit_pending_samples = 0;
            self.unknown_enter_pending_samples = 0;
            self.maybe_transition(
                SemanticState::BlockedOnApproval,
                blocked_reason.to_string(),
                blocked_fingerprint,
            );
            return;
        }

        if self.semantic_state == SemanticState::BlockedOnApproval {
            self.blocked_exit_pending_samples = self.blocked_exit_pending_samples.saturating_add(1);
            if self.blocked_exit_pending_samples < BLOCKED_EXIT_CONFIRM_SAMPLES {
                return;
            }
            self.blocked_exit_pending_samples = 0;
        }

        if is_working {
            self.working_exit_pending_samples = 0;
            self.unknown_enter_pending_samples = 0;
            let reason = if has_thinking {
                "claude:working_thinking"
            } else if has_streaming_tokens {
                "claude:working_streaming_tokens"
            } else if has_running {
                "claude:working_running"
            } else {
                "claude:working_interruptible"
            };
            self.maybe_transition(SemanticState::Working, reason.to_string(), Self::fingerprint_for(SemanticState::Working, reason, &recent));
            return;
        }

        if self.semantic_state == SemanticState::Working {
            self.working_exit_pending_samples = self.working_exit_pending_samples.saturating_add(1);
            if self.working_exit_pending_samples < WORKING_EXIT_CONFIRM_SAMPLES {
                return;
            }
            self.working_exit_pending_samples = 0;
        }

        // CodeAI exited view: Claude now shows a resumable session hint instead of
        // dropping straight back to a bash prompt.
        if codeai_exited_hint {
            self.unknown_enter_pending_samples = 0;
            self.maybe_transition(
                SemanticState::CodeAiExited,
                "CodingAI Exited".to_string(),
                Self::fingerprint_for(SemanticState::CodeAiExited, "CodingAI Exited", &recent),
            );
            return;
        }

        if is_ready {
            self.unknown_enter_pending_samples = 0;
            let ready_reason = if has_ready_shortcuts {
                "claude:ready_shortcuts"
            } else if has_ready_accept_edits {
                "claude:ready_accept_edits"
            } else if has_ready_plan_mode {
                "claude:ready_plan_mode"
            } else if has_ready_try_prompt {
                "claude:ready_try_prompt"
            } else {
                "claude:ready_prompt_visible"
            };
            self.maybe_transition(
                SemanticState::PromptReady,
                ready_reason.to_string(),
                Self::fingerprint_for(SemanticState::PromptReady, ready_reason, &recent),
            );
        } else {
            self.unknown_enter_pending_samples = self.unknown_enter_pending_samples.saturating_add(1);
            if self.unknown_enter_pending_samples < UNKNOWN_FALLBACK_CONFIRM_SAMPLES {
                return;
            }
            self.maybe_transition(
                SemanticState::Unknown,
                "claude:unknown_fallback".to_string(),
                Self::fingerprint_for(SemanticState::Unknown, "claude:unknown_fallback", &recent),
            );
        }
    }
    fn schedule_probe(&self) {
        let shell = format!(
            "zellij --session '{}' action dump-screen /tmp/cc_live_screen.txt >/dev/null 2>&1; awk 'NF {{ blank=0; lines[++n]=$0; next }} !NF {{ blank++; if (blank<=1) lines[++n]=$0 }} END {{ while (n>0 && lines[n] ~ /^$/) n--; start=(n>179?n-179:1); for (i=start; i<=n; i++) print lines[i] }}' /tmp/cc_live_screen.txt",
            self.target_session
        );
        let cmd: Vec<&str> = vec!["sh", "-lc", shell.as_str()];
        run_command(&cmd, BTreeMap::new());
    }
}

impl ZellijPlugin for CodeLeaderVision {
    fn load(&mut self, configuration: BTreeMap<String, String>) {
        request_permission(&[
            PermissionType::ReadApplicationState,
            PermissionType::RunCommands,
        ]);
        set_selectable(true);

        subscribe(&[
            EventType::RunCommandResult,
            EventType::Timer,
        ]);
        set_timeout(1.0);

        if let Some(url) = configuration.get("webhook_url") {
            if !url.trim().is_empty() {
                self.webhook_url = url.clone();
            }
        }
        if let Some(sid) = configuration.get("session_id") {
            if !sid.trim().is_empty() {
                self.session_id = sid.clone();
            }
        }
        if let Some(ts) = configuration.get("target_session") {
            if !ts.trim().is_empty() {
                self.target_session = ts.clone();
            }
        }
        if let Some(tab) = configuration.get("target_tab") {
            if !tab.trim().is_empty() {
                self.target_tab = tab.clone();
            }
        }
        if let Some(role) = configuration.get("target_pane_role") {
            if !role.trim().is_empty() {
                self.target_pane_role = role.clone();
            }
        }
        if let Some(enabled) = configuration.get("webhook_enabled") {
            self.webhook_enabled = !matches!(enabled.as_str(), "0" | "false" | "False" | "FALSE");
        }

        self.last_event_type = "Plugin loaded - claude probe active".to_string();
        self.semantic_state = SemanticState::Unknown;
        self.semantic_reason = "load".to_string();
        self.bootstrap_sync_until_tick = self.tick_count + BOOTSTRAP_SYNC_WINDOW_TICKS;
        self.prompt_ready_reaffirm_budget = 0;
        self.last_semantic_webhook_tick = 0;
        self.last_webhook_seq = 0;
        self.last_screen_hash = 0;
        self.semantic_source = format!(
            "target_probe:{}/{}/{}",
            self.target_session, self.target_tab, self.target_pane_role
        );
    }

    fn update(&mut self, event: Event) -> bool {
        self.tick_count += 1;
        self.event_count += 1;

        match event {
            Event::Timer(_) => {
                self.last_event_type = "Timer:probe".to_string();
                self.last_event_time = format!("tick-{}", self.tick_count);
                
                // Track human input decay
                self.should_emit_human_input(false);

                self.maybe_reaffirm_prompt_ready();
                self.schedule_probe();
                set_timeout(1.0);
            }
            Event::RunCommandResult(exit_code, stdout, stderr, _ctx) => {
                let out = String::from_utf8_lossy(&stdout).to_string();
                let err = String::from_utf8_lossy(&stderr).trim().to_string();
                self.last_event_type = format!(
                    "RunCommandResult:code={:?},out={},err={}",
                    exit_code,
                    if out.trim().is_empty() { "-" } else { "ok" },
                    if err.is_empty() { "-" } else { "yes" }
                );
                self.last_event_time = format!("tick-{}", self.tick_count);
                if !err.is_empty() {
                    self.last_event_type = format!("{} [probe_err]", self.last_event_type);
                }
                let probe_ok = matches!(exit_code, Some(0)) && err.is_empty() && !out.trim().is_empty();
                if probe_ok {
                    self.probe_fail_streak = 0;
                    self.heartbeat_state = HeartbeatState::Ok;
                    self.classify_claude_tui(&out);
                } else {
                    self.probe_fail_streak = self.probe_fail_streak.saturating_add(1);
                    if self.probe_fail_streak >= HEARTBEAT_FAIL_THRESHOLD {
                        self.heartbeat_state = HeartbeatState::Fail;
                    }
                }
            }
            Event::ModeUpdate(mode_info) => {
                self.last_event_type = format!("Mode:{:?}", mode_info.mode);
                self.last_event_time = format!("tick-{}", self.tick_count);
            }
            Event::TabUpdate(tabs) => {
                self.last_event_type = format!("Tabs:{}", tabs.len());
                self.last_event_time = format!("tick-{}", self.tick_count);
            }
            Event::PermissionRequestResult(result) => {
                self.last_event_type = format!("Permission:{:?}", result);
                self.last_event_time = format!("tick-{}", self.tick_count);
            }
            _ => {}
        }

        true
    }
    fn render(&mut self, _rows: usize, _cols: usize) {
        let output = format!(
            "CodeLeader Vision v{}
Ctrl+O: Hide | Ctrl+Q: Quit
════════════  Status ════════════ 
Heartbeat: {}
State: {}
Reason: {}
════════════  Config ════════════ 
Enabled: {}
TargetSession: {}
TargetTab: {}
TargetPaneRole: {}
",
            PLUGIN_VERSION,
            self.heartbeat_state.as_str(),
            self.semantic_state.as_str(),
            self.semantic_reason,
            self.webhook_enabled,
            self.target_session,
            self.target_tab,
            self.target_pane_role,
        );
        print!("{}", output);
    }
}

#[no_mangle]
pub extern "C" fn _start() {}
