"use client";
import { useState, useEffect } from "react";
import axios from "axios";

// --- CÁC INTERFACE KIỂU DỮ LIỆU ---
interface User {
  id_user: number;
  user_name: string;
  email: string;
  role: string;
  total_projects: number;
}

interface AgentLog {
  id_log: number;
  id_project: string;
  agent_name: string;
  action_detail: string;
  status: string;
  created_at: string;
}

interface SystemConfig {
  default_model: string;
  max_testing_retries: number;
  docker_memory_limit: string;
}

export default function AdminDashboard() {
  const [isAdmin, setIsAdmin] = useState<boolean | null>(null);
  const [activeTab, setActiveTab] = useState<"USERS" | "LOGS" | "CONFIG">("USERS");
  
  // States dữ liệu
  const [users, setUsers] = useState<User[]>([]);
  const [logs, setLogs] = useState<AgentLog[]>([]);
  const [config, setConfig] = useState<SystemConfig | null>(null);
  const [isLoading, setIsLoading] = useState(false);

  // 1. KIỂM TRA QUYỀN TRUY CẬP KHI LOAD TRANG
  useEffect(() => {
    const token = localStorage.getItem("token");
    const userStr = localStorage.getItem("user");
    
    if (token && userStr) {
      const userObj = JSON.parse(userStr);
      // Kiểm tra cứng ở client (Backend vẫn chặn ở API)
      if (userObj.role === "ADMIN") {
        axios.defaults.headers.common["Authorization"] = `Bearer ${token}`;
        setIsAdmin(true);
      } else {
        setIsAdmin(false);
      }
    } else {
      setIsAdmin(false);
    }
  }, []);

  // 2. FETCH DỮ LIỆU KHI CHUYỂN TAB
  useEffect(() => {
    if (!isAdmin) return;
    setIsLoading(true);
    
    if (activeTab === "USERS") fetchUsers();
    else if (activeTab === "LOGS") fetchLogs();
    else if (activeTab === "CONFIG") fetchConfig();
    
  }, [activeTab, isAdmin]);

  const fetchUsers = async () => {
    try {
      const res = await axios.get("http://127.0.0.1:8000/api/admin/users");
      setUsers(res.data.users);
    } catch (error) {
      console.error("Lỗi lấy danh sách User", error);
    } finally { setIsLoading(false); }
  };

  const fetchLogs = async () => {
    try {
      const res = await axios.get("http://127.0.0.1:8000/api/admin/logs");
      setLogs(res.data.logs);
    } catch (error) {
      console.error("Lỗi lấy danh sách Logs", error);
    } finally { setIsLoading(false); }
  };

  const fetchConfig = async () => {
    try {
      const res = await axios.get("http://127.0.0.1:8000/api/admin/config");
      setConfig(res.data);
    } catch (error) {
      console.error("Lỗi lấy Cấu hình", error);
    } finally { setIsLoading(false); }
  };

  // 3. CÁC HÀM THAO TÁC (XÓA, CẬP NHẬT)
  const handleDeleteUser = async (id: number, email: string) => {
    if (!window.confirm(`Bạn có chắc muốn xóa tài khoản ${email}? Dữ liệu sẽ mất vĩnh viễn.`)) return;
    try {
      await axios.delete(`http://127.0.0.1:8000/api/admin/users/${id}`);
      setUsers(users.filter(u => u.id_user !== id));
      alert("Đã xóa tài khoản thành công!");
    } catch (error: any) {
      alert(error.response?.data?.detail || "Không thể xóa tài khoản này.");
    }
  };

  const handleUpdateConfig = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!config) return;
    try {
      await axios.put("http://127.0.0.1:8000/api/admin/config", config);
      alert("Cập nhật cấu hình hệ thống thành công!");
    } catch (error) {
      alert("Lỗi khi cập nhật cấu hình.");
    }
  };

  // --- RENDER GIAO DIỆN CHẶN TRUY CẬP ---
  if (isAdmin === false) {
    return (
      <div className="flex h-screen items-center justify-center bg-gray-100">
        <div className="text-center p-8 bg-white rounded-xl shadow-lg">
          <h2 className="text-2xl font-bold text-red-600 mb-2">Truy cập bị từ chối ⛔</h2>
          <p className="text-gray-600 mb-6">Bạn không có quyền quản trị viên để xem trang này.</p>
          <a href="/" className="px-6 py-2 bg-blue-600 text-white rounded hover:bg-blue-700 transition">
            Quay lại trang chính
          </a>
        </div>
      </div>
    );
  }

  // --- RENDER GIAO DIỆN DASHBOARD ADMIN ---
  return (
    <div className="flex h-screen bg-gray-50 text-gray-800 font-sans">
      
      {/* SIDEBAR */}
      <div className="w-64 bg-slate-900 text-white flex flex-col shadow-xl z-10">
        <div className="p-6 border-b border-slate-800">
          <h1 className="text-xl font-bold tracking-wider text-center text-blue-400">ADMIN PANEL</h1>
          <p className="text-xs text-center text-slate-400 mt-1">SDLC Automation</p>
        </div>
        <div className="flex-1 p-4 space-y-2">
          <button 
            onClick={() => setActiveTab("USERS")}
            className={`w-full text-left px-4 py-3 rounded-lg transition ${activeTab === "USERS" ? "bg-blue-600 text-white shadow-md" : "text-slate-300 hover:bg-slate-800"}`}
          >
            👥 Quản lý người dùng
          </button>
          <button 
            onClick={() => setActiveTab("LOGS")}
            className={`w-full text-left px-4 py-3 rounded-lg transition ${activeTab === "LOGS" ? "bg-blue-600 text-white shadow-md" : "text-slate-300 hover:bg-slate-800"}`}
          >
            📋 Nhật ký hoạt động (Logs)
          </button>
          <button 
            onClick={() => setActiveTab("CONFIG")}
            className={`w-full text-left px-4 py-3 rounded-lg transition ${activeTab === "CONFIG" ? "bg-blue-600 text-white shadow-md" : "text-slate-300 hover:bg-slate-800"}`}
          >
            ⚙️ Cấu hình hệ thống
          </button>
        </div>
        <div className="p-4 border-t border-slate-800">
          <a href="/" className="flex items-center justify-center w-full py-2 bg-slate-800 hover:bg-slate-700 text-sm text-slate-300 rounded transition">
            🔙 Quay lại Workspace
          </a>
        </div>
      </div>

      {/* MAIN CONTENT AREA */}
      <div className="flex-1 flex flex-col overflow-hidden">
        <div className="bg-white px-8 py-5 shadow-sm border-b flex justify-between items-center">
          <h2 className="text-2xl font-bold text-slate-800">
            {activeTab === "USERS" && "Quản lý Người dùng"}
            {activeTab === "LOGS" && "Nhật ký Hoạt động Hệ thống"}
            {activeTab === "CONFIG" && "Cấu hình Tham số Hệ thống"}
          </h2>
        </div>

        <div className="flex-1 overflow-auto p-8 bg-slate-50">
          {isLoading ? (
            <div className="flex justify-center mt-20 text-gray-400 animate-pulse">Đang tải dữ liệu...</div>
          ) : (
            <>
              {/* TAB 1: QUẢN LÝ NGƯỜI DÙNG */}
              {activeTab === "USERS" && (
                <div className="bg-white rounded-xl shadow border overflow-hidden">
                  <table className="w-full text-left border-collapse">
                    <thead className="bg-slate-100 text-slate-600 text-sm uppercase">
                      <tr>
                        <th className="py-4 px-6 font-semibold">ID</th>
                        <th className="py-4 px-6 font-semibold">Tên người dùng</th>
                        <th className="py-4 px-6 font-semibold">Email</th>
                        <th className="py-4 px-6 font-semibold">Vai trò</th>
                        <th className="py-4 px-6 font-semibold text-center">Số Dự án</th>
                        <th className="py-4 px-6 font-semibold text-right">Hành động</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-gray-100 text-sm">
                      {users.map(u => (
                        <tr key={u.id_user} className="hover:bg-slate-50 transition">
                          <td className="py-4 px-6 font-medium text-slate-900">#{u.id_user}</td>
                          <td className="py-4 px-6">{u.user_name}</td>
                          <td className="py-4 px-6 text-blue-600">{u.email}</td>
                          <td className="py-4 px-6">
                            <span className={`px-2 py-1 rounded-full text-xs font-bold ${u.role === 'ADMIN' ? 'bg-purple-100 text-purple-700' : 'bg-gray-100 text-gray-700'}`}>
                              {u.role}
                            </span>
                          </td>
                          <td className="py-4 px-6 text-center font-bold">{u.total_projects}</td>
                          <td className="py-4 px-6 text-right">
                            <button 
                              onClick={() => handleDeleteUser(u.id_user, u.email)}
                              className="text-red-500 hover:text-red-700 hover:bg-red-50 px-3 py-1 rounded transition"
                            >
                              Xóa
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}

              {/* TAB 2: NHẬT KÝ LOGS */}
              {activeTab === "LOGS" && (
                <div className="bg-white rounded-xl shadow border overflow-hidden">
                  <table className="w-full text-left border-collapse">
                    <thead className="bg-slate-100 text-slate-600 text-sm uppercase">
                      <tr>
                        <th className="py-4 px-6 font-semibold">Thời gian</th>
                        <th className="py-4 px-6 font-semibold">Dự án (ID)</th>
                        <th className="py-4 px-6 font-semibold">Agent</th>
                        <th className="py-4 px-6 font-semibold w-1/3">Hành động chi tiết</th>
                        <th className="py-4 px-6 font-semibold text-center">Trạng thái</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-gray-100 text-sm">
                      {logs.map(log => (
                        <tr key={log.id_log} className="hover:bg-slate-50 transition">
                          <td className="py-4 px-6 text-gray-500">{new Date(log.created_at).toLocaleString('vi-VN')}</td>
                          <td className="py-4 px-6 font-mono text-xs text-blue-600">{log.id_project.substring(0, 8)}...</td>
                          <td className="py-4 px-6 font-semibold text-slate-700">{log.agent_name}</td>
                          <td className="py-4 px-6 text-gray-600 truncate max-w-xs" title={log.action_detail}>
                            {log.action_detail}
                          </td>
                          <td className="py-4 px-6 text-center">
                            <span className={`px-2 py-1 rounded-full text-xs font-bold ${
                              log.status === 'SUCCESS' ? 'bg-green-100 text-green-700' : 
                              log.status === 'FAILED' ? 'bg-red-100 text-red-700' : 'bg-yellow-100 text-yellow-700'
                            }`}>
                              {log.status}
                            </span>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}

              {/* TAB 3: CẤU HÌNH HỆ THỐNG */}
              {activeTab === "CONFIG" && config && (
                <div className="max-w-2xl bg-white rounded-xl shadow border p-8">
                  <form onSubmit={handleUpdateConfig} className="space-y-6">
                    <div>
                      <label className="block text-sm font-semibold text-gray-700 mb-2">Mô hình AI mặc định (Default Model)</label>
                      <input 
                        type="text" 
                        value={config.default_model}
                        onChange={(e) => setConfig({...config, default_model: e.target.value})}
                        className="w-full px-4 py-2 border rounded-lg focus:ring-2 focus:ring-blue-500 outline-none"
                      />
                      <p className="text-xs text-gray-500 mt-1">Ví dụ: deepseek-chat, gemini-1.5-pro</p>
                    </div>
                    
                    <div>
                      <label className="block text-sm font-semibold text-gray-700 mb-2">Số lần Testing Agent tự sửa lỗi tối đa (Max Retries)</label>
                      <input 
                        type="number" 
                        value={config.max_testing_retries}
                        onChange={(e) => setConfig({...config, max_testing_retries: Number(e.target.value)})}
                        className="w-full px-4 py-2 border rounded-lg focus:ring-2 focus:ring-blue-500 outline-none"
                      />
                    </div>

                    <div>
                      <label className="block text-sm font-semibold text-gray-700 mb-2">Giới hạn RAM cho mỗi Container Sandbox</label>
                      <input 
                        type="text" 
                        value={config.docker_memory_limit}
                        onChange={(e) => setConfig({...config, docker_memory_limit: e.target.value})}
                        className="w-full px-4 py-2 border rounded-lg focus:ring-2 focus:ring-blue-500 outline-none"
                      />
                      <p className="text-xs text-gray-500 mt-1">Ví dụ: 512m, 1g</p>
                    </div>

                    <div className="pt-4 border-t">
                      <button type="submit" className="px-6 py-2 bg-green-600 hover:bg-green-700 text-white font-semibold rounded-lg shadow transition">
                        💾 Lưu Cấu hình
                      </button>
                    </div>
                  </form>
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}