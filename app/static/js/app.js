// Dashboard active states & settings
let activeTab = 'dashboard';
let activeUserId = null;
let refreshInterval = null;

// DOM Elements
const tabButtons = document.querySelectorAll('.nav-item');
const tabPanes = document.querySelectorAll('.tab-pane');
const tabTitle = document.getElementById('tab-title');
const tabSubtitle = document.getElementById('tab-subtitle');
const btnRefresh = document.getElementById('btn-refresh');

// Initialize Dashboard
document.addEventListener('DOMContentLoaded', () => {
    setupTabSwitching();
    loadDashboardData();
    setupForms();
    setupModal();
    setupInboxSearch();
    
    // Start automated background update loop (every 5 seconds)
    refreshInterval = setInterval(automatedRefresh, 5000);
    
    // Wire refresh button
    btnRefresh.addEventListener('click', () => {
        loadTabContent(activeTab, true);
    });
});

// Tab navigation controller
function setupTabSwitching() {
    tabButtons.forEach(btn => {
        btn.addEventListener('click', () => {
            const tabId = btn.getAttribute('data-tab');
            
            // Remove active classes
            tabButtons.forEach(b => b.classList.remove('active'));
            tabPanes.forEach(p => p.classList.remove('active'));
            
            // Add active class
            btn.classList.add('active');
            document.getElementById(`${tabId}-tab`).classList.add('active');
            
            activeTab = tabId;
            updateHeaderTitles(tabId);
            loadTabContent(tabId);
        });
    });
}

function updateHeaderTitles(tabId) {
    switch(tabId) {
        case 'dashboard':
            tabTitle.textContent = "Dashboard Overview";
            tabSubtitle.textContent = "Real-time metrics and configurations for your Instagram automation.";
            break;
        case 'accounts':
            tabTitle.textContent = "Instagram Page Accounts";
            tabSubtitle.textContent = "Manage Meta access credentials and active Instagram business channels.";
            break;
        case 'inbox':
            tabTitle.textContent = "Customer Inbox";
            tabSubtitle.textContent = "Review conversations and inspect webhook agent replies.";
            break;
        case 'logs':
            tabTitle.textContent = "Live Webhook Payload Logs";
            tabSubtitle.textContent = "Raw payloads received from Facebook/Meta in real time.";
            break;
    }
}

// Data dispatch loader
function loadTabContent(tabId, force = false) {
    if (tabId === 'dashboard') {
        loadStats();
    } else if (tabId === 'accounts') {
        loadAccounts();
    } else if (tabId === 'inbox') {
        loadInbox(force);
    } else if (tabId === 'logs') {
        loadLogs();
    }
}

// Background auto-refresh loop
function automatedRefresh() {
    if (activeTab === 'dashboard') {
        loadStats(true);
    } else if (activeTab === 'logs') {
        loadLogs(true);
    } else if (activeTab === 'inbox') {
        if (activeUserId) {
            loadChatHistory(activeUserId, true);
        }
    }
}

function loadDashboardData() {
    loadStats();
    // Configure webhook helper text using location host
    const currentHost = window.location.origin;
    document.getElementById('callback-url-val').textContent = `${currentHost}/webhook`;
}

// Stats & configuration getter
async function loadStats(silent = false) {
    try {
        const response = await fetch('/api/admin/stats');
        if (!response.ok) throw new Error("Failed to fetch stats");
        const stats = await response.json();
        
        document.getElementById('stats-total-payloads').textContent = stats.total_payloads;
        document.getElementById('stats-failed-payloads').textContent = stats.failed_payloads;
        document.getElementById('stats-total-users').textContent = stats.total_users;
        document.getElementById('stats-total-messages').textContent = stats.total_messages;
        
        if (!silent) {
            document.getElementById('sys-api-ver').textContent = stats.api_version || 'v20.0';
            document.getElementById('verify-token-val').textContent = stats.verify_token || 'Not Configured';
        }
    } catch (err) {
        console.error("Stats load error:", err);
    }
}

// Account CRUD Handlers
async function loadAccounts() {
    const tbody = document.getElementById('accounts-tbody');
    try {
        const response = await fetch('/api/admin/accounts');
        if (!response.ok) throw new Error("Failed to fetch accounts");
        const accounts = await response.json();
        
        if (accounts.length === 0) {
            tbody.innerHTML = `<tr><td colspan="3" class="text-center text-muted">No accounts registered yet.</td></tr>`;
            return;
        }
        
        tbody.innerHTML = accounts.map(acc => {
            const tokenPreview = acc.page_access_token 
                ? `${acc.page_access_token.substring(0, 10)}... (Masked)` 
                : 'No Token';
            return `
                <tr>
                    <td class="font-mono">${acc.instagram_business_id}</td>
                    <td class="text-muted font-mono">${tokenPreview}</td>
                    <td>
                        <button class="btn btn-danger btn-sm" onclick="deleteAccount('${acc.instagram_business_id}')">
                            <i class="fa-solid fa-trash"></i> Delete
                        </button>
                    </td>
                </tr>
            `;
        }).join('');
    } catch (err) {
        tbody.innerHTML = `<tr><td colspan="3" class="text-center text-muted error">Error loading accounts.</td></tr>`;
        console.error(err);
    }
}

function setupForms() {
    const form = document.getElementById('form-add-account');
    form.addEventListener('submit', async (e) => {
        e.preventDefault();
        const businessId = document.getElementById('input-business-id').value;
        const token = document.getElementById('input-access-token').value;
        
        try {
            const response = await fetch('/api/admin/accounts', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    instagram_business_id: businessId,
                    page_access_token: token
                })
            });
            
            const result = await response.json();
            if (!response.ok) throw new Error(result.detail || "Failed to register account");
            
            alert("Account registered successfully!");
            form.reset();
            loadAccounts();
        } catch (err) {
            alert(`Error: ${err.message}`);
        }
    });
}

async function deleteAccount(businessId) {
    if (!confirm(`Are you sure you want to delete credentials for account ${businessId}?`)) return;
    
    try {
        const response = await fetch(`/api/admin/accounts/${businessId}`, { method: 'DELETE' });
        const result = await response.json();
        if (!response.ok) throw new Error(result.detail || "Failed to delete account");
        
        alert("Account deleted successfully!");
        loadAccounts();
    } catch (err) {
        alert(`Error: ${err.message}`);
    }
}

// Tracked Users & Chat inbox functions
let allUsers = [];

async function loadInbox(force = false) {
    if (allUsers.length > 0 && !force) return; // Keep cache
    
    const listContainer = document.getElementById('inbox-users-list');
    try {
        const response = await fetch('/api/admin/users');
        if (!response.ok) throw new Error("Failed to fetch users");
        allUsers = await response.json();
        renderUsersList(allUsers);
    } catch (err) {
        document.getElementById('inbox-users-tbody').innerHTML = `
            <div class="text-center text-muted p-4">Error loading users.</div>
        `;
        console.error(err);
    }
}

function renderUsersList(users) {
    const tbody = document.getElementById('inbox-users-tbody');
    if (users.length === 0) {
        tbody.innerHTML = `<div class="text-center text-muted p-4">No tracked conversations.</div>`;
        return;
    }
    
    tbody.innerHTML = users.map(user => {
        const isActive = user.instagram_user_id === activeUserId ? 'active' : '';
        const initials = user.name ? user.name.substring(0, 2).toUpperCase() : 'U';
        const dateStr = user.last_seen_at ? new Date(user.last_seen_at).toLocaleTimeString() : 'N/A';
        const profilePic = user.profile_pic 
            ? `<img src="${user.profile_pic}" alt="avatar" class="user-avatar" style="object-fit:cover;">`
            : `<div class="user-avatar">${initials}</div>`;
            
        return `
            <div class="inbox-user-item ${isActive}" onclick="selectConversation('${user.instagram_user_id}', '${user.name || 'User'}')">
                ${profilePic}
                <div class="user-details">
                    <span class="user-name">${user.name || `User (${user.instagram_user_id.substring(0, 6)})`}</span>
                    <span class="user-meta">Last seen: ${dateStr}</span>
                </div>
            </div>
        `;
    }).join('');
}

function setupInboxSearch() {
    const searchInput = document.getElementById('inbox-search-input');
    searchInput.addEventListener('input', (e) => {
        const query = e.target.value.toLowerCase().trim();
        if (!query) {
            renderUsersList(allUsers);
            return;
        }
        const filtered = allUsers.filter(u => {
            const nameMatch = u.name && u.name.toLowerCase().includes(query);
            const idMatch = u.instagram_user_id && u.instagram_user_id.includes(query);
            return nameMatch || idMatch;
        });
        renderUsersList(filtered);
    });
}

function selectConversation(userId, userName) {
    activeUserId = userId;
    
    // Highlight item
    const items = document.querySelectorAll('.inbox-user-item');
    items.forEach(item => item.classList.remove('active'));
    
    // Update view state
    document.getElementById('chat-empty-view').classList.add('hide');
    document.getElementById('chat-active-view').classList.remove('hide');
    
    // Populate header
    document.getElementById('chat-header-name').textContent = userName;
    document.getElementById('chat-header-userid').textContent = userId;
    document.getElementById('chat-header-avatar').textContent = userName.substring(0,2).toUpperCase();
    
    // Load chats
    loadChatHistory(userId);
}

async function loadChatHistory(userId, silent = false) {
    const chatContainer = document.getElementById('chat-messages-box');
    try {
        const response = await fetch(`/api/admin/users/${userId}/chat`);
        if (!response.ok) throw new Error("Failed to load chat history");
        const chats = await response.json();
        
        if (chats.length === 0) {
            chatContainer.innerHTML = `<div class="text-center text-muted p-4">No message records found.</div>`;
            return;
        }
        
        const oldScrollHeight = chatContainer.scrollHeight;
        const oldScrollTop = chatContainer.scrollTop;
        const isAtBottom = oldScrollTop + chatContainer.clientHeight >= oldScrollHeight - 50;

        chatContainer.innerHTML = chats.map(msg => {
            const dirClass = msg.direction === 'outgoing' ? 'outgoing' : 'incoming';
            const timestamp = msg.timestamp ? new Date(msg.timestamp).toLocaleTimeString() : '';
            return `
                <div class="message-wrapper ${dirClass}">
                    <div class="message-bubble">
                        ${escapeHtml(msg.text || '')}
                    </div>
                    <span class="message-time">${timestamp}</span>
                </div>
            `;
        }).join('');
        
        // Auto scroll to bottom only on first load or if user is already scrolled to bottom
        if (!silent || isAtBottom) {
            chatContainer.scrollTop = chatContainer.scrollHeight;
        }
    } catch (err) {
        if (!silent) {
            chatContainer.innerHTML = `<div class="text-center text-muted error p-4">Error loading messages.</div>`;
        }
        console.error(err);
    }
}

// Webhook Log Viewer
async function loadLogs(silent = false) {
    const tbody = document.getElementById('logs-tbody');
    try {
        const response = await fetch('/api/admin/payloads');
        if (!response.ok) throw new Error("Failed to fetch payloads");
        const payloads = await response.json();
        
        if (payloads.length === 0) {
            tbody.innerHTML = `<tr><td colspan="4" class="text-center text-muted">No webhook payloads logged yet.</td></tr>`;
            return;
        }
        
        tbody.innerHTML = payloads.map(pay => {
            const dateStr = pay.received_at ? new Date(pay.received_at).toLocaleString() : 'N/A';
            const statusClass = (pay.status || 'received').toLowerCase();
            const rawJsonStr = JSON.stringify(pay.payload || {}, null, 2);
            return `
                <tr>
                    <td class="font-mono">${dateStr}</td>
                    <td class="font-mono">${pay.client_ip || 'N/A'}</td>
                    <td><span class="badge ${statusClass}">${pay.status}</span></td>
                    <td>
                        <button class="btn btn-secondary btn-sm" onclick="showJsonModal(${escapeJsQuote(rawJsonStr)})">
                            <i class="fa-solid fa-code"></i> View Raw JSON
                        </button>
                    </td>
                </tr>
            `;
        }).join('');
    } catch (err) {
        if (!silent) {
            tbody.innerHTML = `<tr><td colspan="4" class="text-center text-muted error">Error loading logs.</td></tr>`;
        }
        console.error(err);
    }
}

// Modal management
let activeJson = "";

function setupModal() {
    const modal = document.getElementById('modal-log-viewer');
    const closeBtn = document.getElementById('btn-close-modal');
    
    closeBtn.addEventListener('click', () => {
        modal.classList.remove('show');
    });
    
    window.addEventListener('click', (e) => {
        if (e.target === modal) {
            modal.classList.remove('show');
        }
    });
}

function showJsonModal(jsonStr) {
    const modal = document.getElementById('modal-log-viewer');
    const codeBlock = document.getElementById('modal-json-block');
    codeBlock.textContent = jsonStr;
    modal.classList.add('show');
}

// Helper utilities
function copyText(elementId) {
    const text = document.getElementById(elementId).textContent;
    navigator.clipboard.writeText(text).then(() => {
        alert("Copied to clipboard!");
    }).catch(err => {
        console.error('Failed to copy: ', err);
    });
}

function escapeHtml(unsafe) {
    return unsafe
         .replace(/&/g, "&amp;")
         .replace(/</g, "&lt;")
         .replace(/>/g, "&gt;")
         .replace(/"/g, "&quot;")
         .replace(/'/g, "&#039;");
}

function escapeJsQuote(str) {
    return JSON.stringify(str);
}
