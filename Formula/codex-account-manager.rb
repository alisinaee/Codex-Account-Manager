class CodexAccountManager < Formula
  desc "Cross-platform Codex account tooling with CLI and local web UI"
  homepage "https://github.com/alisinaee/Codex-Account-Manager"
  url "https://github.com/alisinaee/Codex-Account-Manager/archive/refs/tags/v0.0.1-alpha-test.tar.gz"
  sha256 "bb6382786a6bd4dd923e7bb6c173d809840f74089822c67fc2c489bbf7a23210"
  license "MIT"

  depends_on "python@3.11"

  def install
    inreplace "bin/codex-account",
              "#!/usr/bin/env python3",
              "#!#{Formula["python@3.11"].opt_bin}/python3"

    bin.install "bin/codex-account"
    prefix.install "config.json"
    prefix.install "README.md"
  end

  test do
    assert_match "Local Codex account profile switcher",
                 shell_output("#{bin}/codex-account --help")
  end
end
