import { NavLink, Outlet } from 'react-router-dom'
import { Phone, Search, Settings, Activity, Menu, X } from 'lucide-react'
import { useState } from 'react'

interface NavItem {
  to: string
  icon: React.ReactNode
  label: string
}

const navItems: NavItem[] = [
  { to: '/', icon: <Phone size={20} />, label: 'Softphone' },
  { to: '/search', icon: <Search size={20} />, label: 'Busca Semantica' },
  { to: '/dashboard', icon: <Activity size={20} />, label: 'Dashboard' },
  { to: '/settings', icon: <Settings size={20} />, label: 'Configuracoes' },
]

export function MainLayout() {
  const [sidebarOpen, setSidebarOpen] = useState(true)

  return (
    <div className="app-layout">
      {/* Sidebar */}
      <aside className={`sidebar ${sidebarOpen ? 'open' : 'collapsed'}`}>
        <div className="sidebar-header">
          <div className="logo">
            <Phone size={24} />
            {sidebarOpen && <span>Voice Agent</span>}
          </div>
          <button
            className="sidebar-toggle"
            onClick={() => setSidebarOpen(!sidebarOpen)}
            aria-label={sidebarOpen ? 'Fechar menu' : 'Abrir menu'}
          >
            {sidebarOpen ? <X size={20} /> : <Menu size={20} />}
          </button>
        </div>

        <nav className="sidebar-nav">
          {navItems.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              className={({ isActive }) =>
                `nav-item ${isActive ? 'active' : ''}`
              }
              title={item.label}
            >
              {item.icon}
              {sidebarOpen && <span>{item.label}</span>}
            </NavLink>
          ))}
        </nav>

        <div className="sidebar-footer">
          {sidebarOpen && (
            <div className="version">
              <span>v2.0.0</span>
            </div>
          )}
        </div>
      </aside>

      {/* Main Content */}
      <main className="main-content">
        <Outlet />
      </main>
    </div>
  )
}
