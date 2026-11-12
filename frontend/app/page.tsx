"use client";
import { useState, useEffect } from "react";
import axios from "axios";
import ReactMarkdown from "react-markdown";

interface Message {
  role: "USER" | "AGENT" | "SYSTEM";
  content: string;
  isFinished?: boolean;
  showPreviewBtn?: boolean;
  showDownloadBtn?: boolean;
}

interface Project {
  id_project: string;
  project_name: string;
  project_status: string;
}

interface User {
  id_user: number;
  user_name: string;
  email: string;
  role?: string;
}

interface ModuleAttempt {
  attempt_number: number;
  type: string;
  status: string;
}

interface ModuleItem {
  id_module: number;
  module_key: string;
  module_name: string;
  module_type: string;
  module_order: number;
  status: "PENDING" | "CODING" | "TESTING" | "PASSED" | "FAILED" | "SKIPPED";
  retry_count: number;
  max_retries: number;
  is_testable: boolean;
  attempts: ModuleAttempt[];
}

interface TestExecutionItem {
  id_execution: number;
  id_module: number | null;
  test_type: string;
  status: string;
  total_tests: number;
  passed_tests: number;
  failed_tests: number;
  started_at: string;
  finished_at: string | null;
}

export default function Home() {
  // ==========================================
  // STATE XÁC THỰC (AUTH)
  // ==========================================
  const [isLoggedIn, setIsLoggedIn] = useState(false);
  const [currentUser, setCurrentUser] = useState<User | null>(null);
  const [isRegisterMode, setIsRegisterMode] = useState(false);
  const [authEmail, setAuthEmail] = useState("");
  const [authPassword, setAuthPassword] = useState("");
  const [authName, setAuthName] = useState("");
  const [authError, setAuthError] = useState("");
  const [isAuthLoading, setIsAuthLoading] = useState(false);

  // ==========================================
  // STATE DỰ ÁN VÀ CHAT
  // ==========================================
  const [projects, setProjects] = useState<Project[]>([]);
  const [projectId, setProjectId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [isPreviewLoading, setIsPreviewLoading] = useState(false);
  const [isCreatingProject, setIsCreatingProject] = useState(false);
  const [newProjectName, setNewProjectName] = useState("");

  // ==========================================
  // STATE TIẾN TRÌNH (DAG MODULES & TESTS)
  // ==========================================
  const [activeTab, setActiveTab] = useState<"chat" | "modules" | "tests">("chat");
  const [modules, setModules] = useState<ModuleItem[]>([]);
  const [moduleSummary, setModuleSummary] = useState<{ total: number; passed: number; failed: number; pending: number }>({
    total: 0,
    passed: 0,
    failed: 0,
    pending: 0,
  });
  const [testExecutions, setTestExecutions] = useState<TestExecutionItem[]>([]);
  const [isFetchingProgress, setIsFetchingProgress] = useState(false);

  // Kiểm tra trạng thái đăng nhập khi load trang
  useEffect(() => {
    const token = localStorage.getItem("token");
    const userStr = localStorage.getItem("user");
    if (token && userStr) {
      axios.defaults.headers.common["Authorization"] = `Bearer ${token}`;
      setCurrentUser(JSON.parse(userStr));
      setIsLoggedIn(true);
    }
  }, []);

  // Tự động lấy danh sách dự án khi đã đăng nhập
  useEffect(() => {
    if (isLoggedIn) {
      fetchProjects();
    }
  }, [isLoggedIn]);

  // Polling tiến độ module khi đang loading hoặc khi chọn tab modules/tests
  useEffect(() => {
    if (!projectId) return;

    fetchProgressData(projectId);

    let intervalId: NodeJS.Timeout;
    if (isLoading) {
      // Khi AI đang chạy pipeline, poll mỗi 3 giây để cập nhật tiến độ
      intervalId = setInterval(() => {
        fetchProgressData(projectId);
      }, 3000);
    }

    return () => {
      if (intervalId) clearInterval(intervalId);
    };
  }, [projectId, isLoading]);

  const fetchProgressData = async (id: string) => {
    setIsFetchingProgress(true);
    try {
      const [modRes, testRes] = await Promise.all([
        axios.get(`http://127.0.0.1:8000/api/projects/${id}/modules`),
        axios.get(`http://127.0.0.1:8000/api/projects/${id}/test-executions`),
      ]);
      setModules(modRes.data.modules || []);
      setModuleSummary(modRes.data.summary || { total: 0, passed: 0, failed: 0, pending: 0 });
      setTestExecutions(testRes.data.executions || []);
    } catch (err) {
      console.error("Lỗi lấy tiến độ module & test:", err);
    } finally {
      setIsFetchingProgress(false);
    }
  };

  // ==========================================
  // CÁC HÀM XỬ LÝ AUTH
  // ==========================================
  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsAuthLoading(true);
    setAuthError("");
    try {
      const res = await axios.post("http://127.0.0.1:8000/api/auth/login", {
        email: authEmail,
        password: authPassword,
      });
      const token = res.data.access_token;
      const user = res.data.user;

      localStorage.setItem("token", token);
      localStorage.setItem("user", JSON.stringify(user));
      axios.defaults.headers.common["Authorization"] = `Bearer ${token}`;

      setCurrentUser(user);
      setIsLoggedIn(true);
      setAuthEmail("");
      setAuthPassword("");

      if (user.role === "ADMIN") {
        window.location.href = "/admin";
        return;
      }
    } catch (error: any) {
      setAuthError(error.response?.data?.detail || "Đăng nhập thất bại. Kiểm tra lại thông tin.");
    } finally {
      setIsAuthLoading(false);
    }
  };

  const handleRegister = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsAuthLoading(true);
    setAuthError("");
    try {
      await axios.post("http://127.0.0.1:8000/api/auth/register", {
        user_name: authName,
        email: authEmail,
        password: authPassword,
      });
      alert("Đăng ký thành công! Vui lòng đăng nhập.");
      setIsRegisterMode(false);
      setAuthPassword("");
    } catch (error: any) {
      setAuthError(error.response?.data?.detail || "Lỗi đăng ký. Vui lòng thử lại.");
    } finally {
      setIsAuthLoading(false);
    }
  };

  const handleLogout = () => {
    localStorage.removeItem("token");
    localStorage.removeItem("user");
    delete axios.defaults.headers.common["Authorization"];
    setIsLoggedIn(false);
    setCurrentUser(null);
    setProjects([]);
    setProjectId(null);
    setMessages([]);
    setModules([]);
    setTestExecutions([]);
  };

  // ==========================================
  // CÁC HÀM XỬ LÝ DỰ ÁN VÀ CHAT
  // ==========================================
  const fetchProjects = async () => {
    try {
      const res = await axios.get("http://127.0.0.1:8000/api/projects");
      setProjects(res.data.projects || []);
    } catch (error) {
      console.error("Lỗi lấy danh sách dự án:", error);
    }
  };

  const handleCreateNewProject = async () => {
    if (!newProjectName.trim()) {
      setIsCreatingProject(false);
      return;
    }
    try {
      const res = await axios.post("http://127.0.0.1:8000/api/projects", {
        project_name: newProjectName,
      });
      const newId = res.data.id_project;
      setProjectId(newId);
      setMessages([{ role: "SYSTEM", content: `Đã tạo dự án "${newProjectName}". BA Agent đã sẵn sàng tiếp nhận yêu cầu!` }]);
      setNewProjectName("");
      setIsCreatingProject(false);
      fetchProjects();
      fetchProgressData(newId);
    } catch (error) {
      alert("Không thể tạo dự án. Đảm bảo Backend đang chạy.");
    }
  };

  const handleSelectProject = async (id: string) => {
    setProjectId(id);
    setActiveTab("chat");
    setMessages([{ role: "SYSTEM", content: "Đang tải lịch sử dự án..." }]);
    try {
      const res = await axios.get(`http://127.0.0.1:8000/api/projects/${id}/history`);
      if (res.data.messages.length > 0) {
        setMessages(res.data.messages);
      } else {
        setMessages([{ role: "SYSTEM", content: "Dự án này chưa có lịch sử trò chuyện. Hãy nhập yêu cầu phần mềm để bắt đầu!" }]);
      }
      fetchProgressData(id);
    } catch (error) {
      setMessages([{ role: "SYSTEM", content: "Lỗi khi tải lịch sử dự án." }]);
    }
  };

  const handleDeleteProject = async (e: React.MouseEvent, id: string, name: string) => {
    e.stopPropagation();
    const confirmDelete = window.confirm(`Bạn có chắc muốn xóa dự án "${name}"? Toàn bộ mã nguồn và test sẽ bị xóa.`);
    if (!confirmDelete) return;
    try {
      await axios.delete(`http://127.0.0.1:8000/api/projects/${id}`);
      setProjects((prev) => prev.filter((p) => p.id_project !== id));
      if (projectId === id) {
        setProjectId(null);
        setMessages([]);
        setModules([]);
        setTestExecutions([]);
      }
    } catch (error) {
      alert("Không thể xóa dự án.");
    }
  };

  const handleSendMessage = async () => {
    if (!input.trim() || !projectId) return;
    const userMsg: Message = { role: "USER", content: input };
    setMessages((prev) => [...prev, userMsg]);
    setInput("");
    setIsLoading(true);

    try {
      const res = await axios.post("http://127.0.0.1:8000/api/chat", {
        id_project: projectId,
        prompt: input,
      });
      const aiText = res.data.ai_response;
      const showPreview = aiText.includes("Link Preview") || aiText.includes("chạy trên Docker");
      const showDownload = aiText.includes("Đã đóng gói thành công");

      setMessages((prev) => [
        ...prev,
        {
          role: "AGENT",
          content: aiText,
          isFinished: showPreview || showDownload,
          showPreviewBtn: showPreview,
          showDownloadBtn: showDownload,
        },
      ]);
      fetchProgressData(projectId);
    } catch (error) {
      setMessages((prev) => [...prev, { role: "SYSTEM", content: "Có lỗi xảy ra khi giao tiếp với AI Agent." }]);
    } finally {
      setIsLoading(false);
    }
  };

  const handleDownloadZip = () => {
    if (!projectId) return;
    window.open(`http://127.0.0.1:8000/api/projects/${projectId}/download`, "_blank");
  };

  const handlePreview = async () => {
    if (!projectId) return;
    setIsPreviewLoading(true);
    try {
      const res = await axios.post(`http://127.0.0.1:8000/api/projects/${projectId}/preview`);
      if (res.data.status === "success") {
        if (res.data.preview_url) {
          window.open(res.data.preview_url, "_blank");
        } else {
          alert("🎉 Khởi động thành công! Vui lòng kiểm tra Docker Desktop.");
        }
      } else {
        alert("Có lỗi khi chạy Docker:\n\n" + res.data.logs);
      }
    } catch (error) {
      alert("Hệ thống gặp sự cố khi gọi API khởi chạy Docker.");
    } finally {
      setIsPreviewLoading(false);
    }
  };

  // Helper hiển thị trạng thái module
  const renderModuleStatusBadge = (status: string) => {
    switch (status) {
      case "PASSED":
        return <span className="px-2.5 py-1 text-xs font-semibold rounded-full bg-emerald-100 text-emerald-800 border border-emerald-300">✅ PASSED</span>;
      case "TESTING":
        return <span className="px-2.5 py-1 text-xs font-semibold rounded-full bg-purple-100 text-purple-800 border border-purple-300 animate-pulse">🧪 TESTING</span>;
      case "CODING":
        return <span className="px-2.5 py-1 text-xs font-semibold rounded-full bg-blue-100 text-blue-800 border border-blue-300 animate-pulse">💻 CODING</span>;
      case "FAILED":
        return <span className="px-2.5 py-1 text-xs font-semibold rounded-full bg-red-100 text-red-800 border border-red-300">❌ FAILED</span>;
      case "SKIPPED":
        return <span className="px-2.5 py-1 text-xs font-semibold rounded-full bg-gray-100 text-gray-700 border border-gray-300">⏭️ SKIPPED</span>;
      default:
        return <span className="px-2.5 py-1 text-xs font-semibold rounded-full bg-amber-100 text-amber-800 border border-amber-300">⏳ PENDING</span>;
    }
  };

  // ==========================================
  // GIAO DIỆN AUTH (KHI CHƯA ĐĂNG NHẬP)
  // ==========================================
  if (!isLoggedIn) {
    return (
      <div className="flex h-screen items-center justify-center bg-slate-900 font-sans text-gray-800">
        <div className="w-full max-w-md bg-white p-8 rounded-xl shadow-2xl">
          <h2 className="text-2xl font-bold text-center mb-6 text-slate-800">
            {isRegisterMode ? "Tạo tài khoản mới" : "Đăng nhập hệ thống"}
          </h2>
          {authError && (
            <div className="mb-4 p-3 bg-red-100 border border-red-300 text-red-700 text-sm rounded">
              {authError}
            </div>
          )}
          <form onSubmit={isRegisterMode ? handleRegister : handleLogin} className="space-y-4">
            {isRegisterMode && (
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Họ và tên</label>
                <input
                  type="text"
                  required
                  className="w-full px-4 py-2 border rounded-lg focus:ring-2 focus:ring-blue-500 outline-none"
                  value={authName}
                  onChange={(e) => setAuthName(e.target.value)}
                  placeholder="Nhập họ và tên..."
                />
              </div>
            )}
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Email</label>
              <input
                type="email"
                required
                className="w-full px-4 py-2 border rounded-lg focus:ring-2 focus:ring-blue-500 outline-none"
                value={authEmail}
                onChange={(e) => setAuthEmail(e.target.value)}
                placeholder="Ví dụ: admin@gmail.com"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Mật khẩu</label>
              <input
                type="password"
                required
                minLength={6}
                className="w-full px-4 py-2 border rounded-lg focus:ring-2 focus:ring-blue-500 outline-none"
                value={authPassword}
                onChange={(e) => setAuthPassword(e.target.value)}
                placeholder="Nhập mật khẩu (ít nhất 6 ký tự)"
              />
            </div>
            <button
              type="submit"
              disabled={isAuthLoading}
              className="w-full py-2 bg-blue-600 hover:bg-blue-700 text-white font-semibold rounded-lg transition disabled:bg-blue-400"
            >
              {isAuthLoading ? "Đang xử lý..." : isRegisterMode ? "Đăng ký" : "Đăng nhập"}
            </button>
          </form>
          <div className="mt-6 text-center text-sm text-gray-500">
            {isRegisterMode ? "Đã có tài khoản? " : "Chưa có tài khoản? "}
            <button
              onClick={() => {
                setIsRegisterMode(!isRegisterMode);
                setAuthError("");
              }}
              className="text-blue-600 hover:underline font-medium"
            >
              {isRegisterMode ? "Đăng nhập ngay" : "Tạo tài khoản"}
            </button>
          </div>
        </div>
      </div>
    );
  }

  // ==========================================
  // GIAO DIỆN CHÍNH (KHI ĐÃ ĐĂNG NHẬP)
  // ==========================================
  return (
    <div className="flex h-screen bg-gray-100 font-sans text-gray-800">
      {/* SIDEBAR */}
      <div className="w-64 bg-slate-900 text-white flex flex-col border-r border-slate-800">
        <div className="p-4 bg-slate-950 font-bold text-lg tracking-wider text-center border-b border-slate-800 flex flex-col items-center">
          <span>SDLC AUTOMATION</span>
          <span className="text-xs font-normal text-slate-400 mt-1 bg-slate-800 px-2 py-0.5 rounded-full">
            👤 {currentUser?.user_name}
          </span>
        </div>

        <div className="flex-1 overflow-y-auto p-4 space-y-2 flex flex-col">
          <div className="text-xs text-slate-400 font-semibold mb-2 uppercase">Khu vực làm việc</div>

          {!isCreatingProject ? (
            <button
              onClick={() => setIsCreatingProject(true)}
              className="w-full text-left px-4 py-2 bg-blue-600 rounded-md hover:bg-blue-500 transition shadow mb-2 font-medium"
            >
              + Dự án mới
            </button>
          ) : (
            <div className="mb-2 p-3 bg-slate-800 rounded-md border border-slate-700 shadow-inner">
              <input
                type="text"
                autoFocus
                className="w-full bg-slate-900 text-white px-3 py-2 rounded mb-3 outline-none text-sm border border-slate-600 focus:border-blue-500 transition"
                placeholder="Nhập tên dự án..."
                value={newProjectName}
                onChange={(e) => setNewProjectName(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && handleCreateNewProject()}
              />
              <div className="flex justify-end gap-2">
                <button
                  onClick={() => setIsCreatingProject(false)}
                  className="px-3 py-1 text-xs text-slate-300 hover:text-white bg-slate-700 hover:bg-slate-600 rounded transition"
                >
                  Hủy
                </button>
                <button
                  onClick={handleCreateNewProject}
                  className="px-3 py-1 text-xs bg-blue-600 hover:bg-blue-500 text-white rounded transition"
                >
                  Tạo mới
                </button>
              </div>
            </div>
          )}

          <div className="text-xs text-slate-400 font-semibold mt-4 mb-2 uppercase">Dự án của bạn</div>
          <div className="flex-1 overflow-y-auto space-y-1">
            {projects.map((proj) => (
              <div
                key={proj.id_project}
                className={`flex items-center w-full text-sm rounded-md transition group ${
                  projectId === proj.id_project ? "bg-slate-700 text-white font-medium" : "hover:bg-slate-800 text-slate-300"
                }`}
              >
                <button
                  onClick={() => handleSelectProject(proj.id_project)}
                  className="flex-1 text-left px-3 py-2 truncate"
                  title={proj.project_name}
                >
                  📁 {proj.project_name}
                </button>
                <button
                  onClick={(e) => handleDeleteProject(e, proj.id_project, proj.project_name)}
                  className="opacity-0 group-hover:opacity-100 text-slate-500 hover:text-red-400 transition px-3 py-2"
                  title="Xóa dự án"
                >
                  ✕
                </button>
              </div>
            ))}
            {projects.length === 0 && <div className="text-slate-500 text-sm px-2">Chưa có dự án nào</div>}
          </div>

          <div className="mt-auto border-t border-slate-700 pt-4">
            <button
              onClick={handleLogout}
              className="w-full text-left px-4 py-2 hover:bg-red-600 hover:text-white rounded-md transition text-slate-400 flex items-center gap-2"
            >
              🚪 Đăng xuất
            </button>
          </div>
        </div>
      </div>

      {/* MAIN CONTENT AREA */}
      <div className="flex-1 flex flex-col">
        {projectId ? (
          <>
            {/* TOP BAR & TABS */}
            <div className="bg-white px-6 py-3 shadow-sm border-b flex justify-between items-center">
              <div>
                <h2 className="font-semibold text-lg text-slate-800 flex items-center gap-2">
                  <span>{projects.find((p) => p.id_project === projectId)?.project_name || "Đang kết nối..."}</span>
                  {isLoading && (
                    <span className="flex items-center text-xs font-normal text-blue-600 bg-blue-50 px-2 py-0.5 rounded-full border border-blue-200 animate-pulse">
                      ⚡ Pipeline đang xử lý...
                    </span>
                  )}
                </h2>
                <p className="text-xs text-gray-500">ID: {projectId}</p>
              </div>

              {/* TABS NAVIGATION */}
              <div className="flex items-center bg-gray-100 p-1 rounded-lg border border-gray-200">
                <button
                  onClick={() => setActiveTab("chat")}
                  className={`px-4 py-1.5 text-xs font-semibold rounded-md transition ${
                    activeTab === "chat" ? "bg-white text-blue-600 shadow-sm" : "text-gray-600 hover:text-gray-900"
                  }`}
                >
                  💬 Hội thoại (Chat)
                </button>
                <button
                  onClick={() => setActiveTab("modules")}
                  className={`px-4 py-1.5 text-xs font-semibold rounded-md transition flex items-center gap-1.5 ${
                    activeTab === "modules" ? "bg-white text-blue-600 shadow-sm" : "text-gray-600 hover:text-gray-900"
                  }`}
                >
                  <span>🧩 Modules DAG</span>
                  {moduleSummary.total > 0 && (
                    <span className="px-1.5 py-0.2 bg-blue-100 text-blue-800 rounded-full text-[10px]">
                      {moduleSummary.passed}/{moduleSummary.total}
                    </span>
                  )}
                </button>
                <button
                  onClick={() => setActiveTab("tests")}
                  className={`px-4 py-1.5 text-xs font-semibold rounded-md transition flex items-center gap-1.5 ${
                    activeTab === "tests" ? "bg-white text-blue-600 shadow-sm" : "text-gray-600 hover:text-gray-900"
                  }`}
                >
                  <span>🧪 Lịch sử Test</span>
                  {testExecutions.length > 0 && (
                    <span className="px-1.5 py-0.2 bg-purple-100 text-purple-800 rounded-full text-[10px]">
                      {testExecutions.length}
                    </span>
                  )}
                </button>
              </div>
            </div>

            {/* TAB 1: CHAT */}
            {activeTab === "chat" && (
              <div className="flex-1 flex flex-col overflow-hidden">
                <div className="flex-1 p-6 overflow-y-auto bg-gray-50 flex flex-col gap-4">
                  {messages.map((msg, idx) => (
                    <div key={idx} className={`flex ${msg.role === "USER" ? "justify-end" : "justify-start"}`}>
                      <div
                        className={`max-w-3xl p-4 rounded-xl shadow-sm ${
                          msg.role === "USER"
                            ? "bg-blue-600 text-white rounded-br-none"
                            : msg.role === "SYSTEM"
                            ? "bg-gray-200 text-gray-700 text-sm text-center mx-auto rounded-full px-6"
                            : "bg-white border border-gray-200 text-gray-800 rounded-bl-none"
                        }`}
                      >
                        <div className="whitespace-pre-wrap leading-relaxed space-y-2">
                          <ReactMarkdown
                            components={{
                              a: ({ node, ...props }) => (
                                <a
                                  {...props}
                                  target="_blank"
                                  rel="noopener noreferrer"
                                  className="text-blue-600 hover:text-blue-800 font-bold underline cursor-pointer"
                                />
                              ),
                              code: ({ node, inline, ...props }: any) =>
                                inline ? (
                                  <code {...props} className="bg-gray-100 text-red-500 px-1 py-0.5 rounded text-sm font-mono" />
                                ) : (
                                  <code {...props} className="block bg-gray-900 text-green-400 p-3 rounded text-sm overflow-x-auto my-2 font-mono" />
                                ),
                              h3: ({ node, ...props }) => <h3 {...props} className="text-lg font-bold text-gray-800 mt-3" />,
                            }}
                          >
                            {msg.content}
                          </ReactMarkdown>
                        </div>
                        {msg.isFinished && (
                          <div className="mt-4 p-4 bg-emerald-50 border border-emerald-200 rounded-lg">
                            <h4 className="font-bold text-emerald-800 mb-2">
                              {msg.showDownloadBtn ? "📦 Dự án đã sẵn sàng tải về!" : "🎉 Dự án đã hoàn thành các vòng kiểm thử!"}
                            </h4>
                            <div className="flex gap-3 mt-3">
                              {msg.showPreviewBtn && (
                                <button
                                  onClick={handlePreview}
                                  disabled={isPreviewLoading}
                                  className="px-4 py-2 bg-emerald-600 text-white text-sm font-semibold rounded shadow hover:bg-emerald-700 transition disabled:bg-emerald-400 flex items-center gap-2"
                                >
                                  {isPreviewLoading ? "Đang khởi chạy..." : "▶ Mở Preview (Docker)"}
                                </button>
                              )}
                              {msg.showDownloadBtn && (
                                <button
                                  onClick={handleDownloadZip}
                                  className="px-4 py-2 bg-blue-600 text-white text-sm font-semibold rounded shadow hover:bg-blue-700 transition flex items-center gap-2"
                                >
                                  ⬇ Tải mã nguồn (.ZIP)
                                </button>
                              )}
                            </div>
                          </div>
                        )}
                      </div>
                    </div>
                  ))}
                  {isLoading && (
                    <div className="bg-white border border-blue-200 text-blue-700 rounded-xl rounded-bl-none p-4 shadow-sm w-fit flex items-center gap-3">
                      <div className="w-4 h-4 border-2 border-blue-600 border-t-transparent rounded-full animate-spin"></div>
                      <span>Các Multi-Agent đang suy nghĩ và thực thi kiểm thử...</span>
                    </div>
                  )}
                </div>

                <div className="bg-white p-4 border-t">
                  <div className="max-w-4xl mx-auto flex gap-3">
                    <input
                      type="text"
                      className="flex-1 bg-gray-100 focus:bg-white focus:border-blue-500 focus:ring-2 focus:ring-blue-200 rounded-lg px-4 py-3 outline-none transition text-black"
                      placeholder="Nhập yêu cầu ban đầu hoặc feedback sửa lỗi..."
                      value={input}
                      onChange={(e) => setInput(e.target.value)}
                      onKeyDown={(e) => e.key === "Enter" && handleSendMessage()}
                      disabled={isLoading}
                    />
                    <button
                      onClick={handleSendMessage}
                      disabled={isLoading}
                      className="bg-blue-600 hover:bg-blue-700 text-white px-6 py-3 rounded-lg font-semibold shadow disabled:bg-gray-400 transition"
                    >
                      Gửi yêu cầu
                    </button>
                  </div>
                </div>
              </div>
            )}

            {/* TAB 2: DAG MODULES VIEW */}
            {activeTab === "modules" && (
              <div className="flex-1 p-6 overflow-y-auto bg-gray-50 flex flex-col gap-6">
                {/* SUMMARY STATS */}
                <div className="grid grid-cols-4 gap-4">
                  <div className="bg-white p-4 rounded-xl border border-gray-200 shadow-sm flex flex-col">
                    <span className="text-xs text-gray-500 uppercase font-semibold">Tổng Module</span>
                    <span className="text-2xl font-bold text-slate-800 mt-1">{moduleSummary.total}</span>
                  </div>
                  <div className="bg-white p-4 rounded-xl border border-emerald-200 bg-emerald-50/30 shadow-sm flex flex-col">
                    <span className="text-xs text-emerald-700 uppercase font-semibold">Đã PASSED</span>
                    <span className="text-2xl font-bold text-emerald-600 mt-1">{moduleSummary.passed}</span>
                  </div>
                  <div className="bg-white p-4 rounded-xl border border-red-200 bg-red-50/30 shadow-sm flex flex-col">
                    <span className="text-xs text-red-700 uppercase font-semibold">Thất bại (FAILED)</span>
                    <span className="text-2xl font-bold text-red-600 mt-1">{moduleSummary.failed}</span>
                  </div>
                  <div className="bg-white p-4 rounded-xl border border-amber-200 bg-amber-50/30 shadow-sm flex flex-col">
                    <span className="text-xs text-amber-700 uppercase font-semibold">Đang chờ (PENDING)</span>
                    <span className="text-2xl font-bold text-amber-600 mt-1">{moduleSummary.pending}</span>
                  </div>
                </div>

                {/* MODULES LIST */}
                <div className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden">
                  <div className="p-4 border-b border-gray-200 bg-gray-50 flex justify-between items-center">
                    <h3 className="font-semibold text-slate-800">Đồ thị phát triển Module (Topological Order)</h3>
                    <button
                      onClick={() => fetchProgressData(projectId)}
                      className="text-xs text-blue-600 hover:text-blue-800 font-medium"
                    >
                      🔄 Làm mới
                    </button>
                  </div>

                  {modules.length === 0 ? (
                    <div className="p-8 text-center text-gray-400 text-sm">
                      Chưa có danh sách module. Khi BA Agent hoàn tất phân tích yêu cầu, Design Agent sẽ sinh cấu trúc module tự động tại đây.
                    </div>
                  ) : (
                    <div className="divide-y divide-gray-100">
                      {modules.map((mod, idx) => (
                        <div key={mod.id_module} className="p-4 hover:bg-slate-50 transition flex items-center justify-between">
                          <div className="flex items-center gap-4">
                            <span className="w-8 h-8 rounded-full bg-slate-100 text-slate-700 font-bold flex items-center justify-center text-sm border border-slate-200">
                              {idx + 1}
                            </span>
                            <div>
                              <div className="flex items-center gap-2">
                                <h4 className="font-semibold text-slate-800">{mod.module_key}</h4>
                                <span className="text-[11px] px-2 py-0.5 rounded bg-gray-100 text-gray-600 border border-gray-200 uppercase font-mono">
                                  {mod.module_type}
                                </span>
                                {!mod.is_testable && (
                                  <span className="text-[10px] text-gray-500 italic">
                                    (Không cần test)
                                  </span>
                                )}
                              </div>
                              <p className="text-xs text-gray-500 mt-0.5">{mod.module_name}</p>
                              {mod.attempts && mod.attempts.length > 0 && (
                                <div className="flex gap-2 mt-1.5">
                                  {mod.attempts.map((att, aIdx) => (
                                    <span
                                      key={aIdx}
                                      className={`text-[10px] px-1.5 py-0.5 rounded border ${
                                        att.status === "SUCCESS"
                                          ? "bg-emerald-50 text-emerald-700 border-emerald-200"
                                          : att.status === "FAILED"
                                          ? "bg-red-50 text-red-700 border-red-200"
                                          : "bg-blue-50 text-blue-700 border-blue-200"
                                      }`}
                                    >
                                      Lần {att.attempt_number} ({att.type}): {att.status}
                                    </span>
                                  ))}
                                </div>
                              )}
                            </div>
                          </div>

                          <div className="flex items-center gap-4">
                            <div className="text-right">
                              <div className="text-xs text-gray-400">Số lần sửa lỗi</div>
                              <div className="text-xs font-semibold text-slate-700">
                                {mod.retry_count} / {mod.max_retries}
                              </div>
                            </div>
                            {renderModuleStatusBadge(mod.status)}
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            )}

            {/* TAB 3: TEST EXECUTIONS VIEW */}
            {activeTab === "tests" && (
              <div className="flex-1 p-6 overflow-y-auto bg-gray-50 flex flex-col gap-6">
                <div className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden">
                  <div className="p-4 border-b border-gray-200 bg-gray-50 flex justify-between items-center">
                    <div>
                      <h3 className="font-semibold text-slate-800">Lịch sử chạy kiểm thử (Unit Test & System Test)</h3>
                      <p className="text-xs text-gray-500 mt-0.5">Tất cả bài test được chạy cô lập trong Docker Sandbox</p>
                    </div>
                    <button
                      onClick={() => fetchProgressData(projectId)}
                      className="text-xs text-blue-600 hover:text-blue-800 font-medium"
                    >
                      🔄 Làm mới
                    </button>
                  </div>

                  {testExecutions.length === 0 ? (
                    <div className="p-8 text-center text-gray-400 text-sm">
                      Chưa có bài kiểm thử nào được thực thi.
                    </div>
                  ) : (
                    <div className="overflow-x-auto">
                      <table className="w-full text-left text-sm text-gray-600">
                        <thead className="bg-gray-50 text-xs uppercase text-gray-500 border-b border-gray-200">
                          <tr>
                            <th className="px-4 py-3">ID</th>
                            <th className="px-4 py-3">Loại Test</th>
                            <th className="px-4 py-3">Trạng thái</th>
                            <th className="px-4 py-3">Tổng số</th>
                            <th className="px-4 py-3">Passed</th>
                            <th className="px-4 py-3">Failed</th>
                            <th className="px-4 py-3">Thời gian</th>
                          </tr>
                        </thead>
                        <tbody className="divide-y divide-gray-100">
                          {testExecutions.map((exec) => (
                            <tr key={exec.id_execution} className="hover:bg-slate-50 transition">
                              <td className="px-4 py-3 font-mono text-xs">#{exec.id_execution}</td>
                              <td className="px-4 py-3">
                                <span
                                  className={`px-2 py-0.5 text-xs rounded font-semibold ${
                                    exec.test_type === "INTEGRATION"
                                      ? "bg-purple-100 text-purple-700"
                                      : "bg-blue-100 text-blue-700"
                                  }`}
                                >
                                  {exec.test_type}
                                </span>
                              </td>
                              <td className="px-4 py-3">
                                {exec.status === "PASSED" ? (
                                  <span className="text-emerald-600 font-semibold text-xs flex items-center gap-1">
                                    ✅ PASSED
                                  </span>
                                ) : exec.status === "FAILED" ? (
                                  <span className="text-red-600 font-semibold text-xs flex items-center gap-1">
                                    ❌ FAILED
                                  </span>
                                ) : (
                                  <span className="text-blue-600 font-semibold text-xs animate-pulse">
                                    ⏳ RUNNING
                                  </span>
                                )}
                              </td>
                              <td className="px-4 py-3 font-medium">{exec.total_tests}</td>
                              <td className="px-4 py-3 text-emerald-600 font-medium">{exec.passed_tests}</td>
                              <td className="px-4 py-3 text-red-600 font-medium">{exec.failed_tests}</td>
                              <td className="px-4 py-3 text-xs text-gray-400">
                                {exec.started_at ? new Date(exec.started_at).toLocaleTimeString() : "-"}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                </div>
              </div>
            )}
          </>
        ) : (
          <div className="flex-1 flex items-center justify-center bg-gray-50 text-gray-400">
            Hãy chọn một dự án bên trái hoặc tạo dự án mới để bắt đầu.
          </div>
        )}
      </div>
    </div>
  );
}
