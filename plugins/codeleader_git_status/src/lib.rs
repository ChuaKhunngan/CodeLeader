use std::collections::BTreeMap;
use zellij_tile::prelude::*;

#[derive(Default)]
struct CodeLeaderGitStatus {
    repo_dir: String,
    remote_host: String,
    git_status_text: String,
    tick_count: u64,
}

register_plugin!(CodeLeaderGitStatus);

impl ZellijPlugin for CodeLeaderGitStatus {
    fn load(&mut self, configuration: BTreeMap<String, String>) {
        request_permission(&[PermissionType::RunCommands]);
        set_selectable(true);
        subscribe(&[EventType::Timer, EventType::RunCommandResult]);

        if let Some(dir) = configuration.get("repo_dir") {
            self.repo_dir = dir.clone();
        } else {
            self.repo_dir = ".".to_string();
        }
        if let Some(host) = configuration.get("remote_host") {
            self.remote_host = host.clone();
        } else {
            self.remote_host = "unknown".to_string();
        }

        self.git_status_text = "Loading Git Status...".to_string();
        set_timeout(1.0);
    }

    fn update(&mut self, event: Event) -> bool {
        match event {
            Event::Timer(_) => {
                self.tick_count += 1;
                if self.tick_count % 3 == 0 || self.tick_count == 1 {
                    let shell_cmd = format!(
                        "cd '{}' 2>/dev/null && \
                        if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then \
                            echo '__GIT_OK__'; \
                            git log -n 5 --oneline; \
                            echo '__GIT_STAGE_START__'; \
                            git status --short | head -n 30; \
                        else \
                            echo '__GIT_FAIL__'; \
                        fi",
                        self.repo_dir
                    );
                    let cmd: Vec<&str> = vec!["bash", "-c", &shell_cmd];
                    run_command(&cmd, BTreeMap::new());
                }
                set_timeout(1.0);
            }
            Event::RunCommandResult(_exit_code, stdout, _stderr, _ctx) => {
                let out = String::from_utf8_lossy(&stdout).to_string();
                if out.contains("__GIT_FAIL__") {
                    self.git_status_text = "Repository Not Initialized".to_string();
                } else if out.contains("__GIT_OK__") {
                    let mut display = String::new();
                    display.push_str("════════════ Commits ════════════\n");
                    
                    let parts: Vec<&str> = out.split("__GIT_STAGE_START__").collect();
                    if parts.len() == 2 {
                        let log_part = parts[0].replace("__GIT_OK__\n", "").replace("__GIT_OK__", "");
                        let status_part = parts[1];
                        
                        let logs = log_part.trim();
                        if logs.is_empty() {
                            display.push_str("No commits yet.\n");
                        } else {
                            display.push_str(logs);
                            display.push('\n');
                        }
                        
                        display.push_str("\n══════════ Uncommitted ══════════\n");
                        let statusstr = status_part.trim();
                        if statusstr.is_empty() {
                            display.push_str("Working directory clean.\n");
                        } else {
                            display.push_str(statusstr);
                            display.push('\n');
                        }
                    }
                    self.git_status_text = display;
                }
            }
            _ => {}
        }
        true
    }

    fn render(&mut self, _rows: usize, _cols: usize) {
        println!("Host: {}", self.remote_host);
        println!("Repo Dir: {}\n", self.repo_dir);
        println!("{}", self.git_status_text);
    }
}

#[no_mangle]
pub extern "C" fn _start() {}
