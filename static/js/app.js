// Common functions for all pages

// Theme management
function initTheme() {
    const savedTheme = localStorage.getItem('iabs-theme') || 'dark';
    if (savedTheme === 'light') {
        document.body.classList.add('light-theme');
    }
}

function toggleTheme() {
    document.body.classList.toggle('light-theme');
    const currentTheme = document.body.classList.contains('light-theme') ? 'light' : 'dark';
    localStorage.setItem('iabs-theme', currentTheme);
}

// Initialize theme on page load
initTheme();

function openModal(modalId) {
    document.getElementById(modalId).classList.add('active');
}

function closeModal(modalId) {
    document.getElementById(modalId).classList.remove('active');
}

async function logout() {
    await fetch('/api/logout', { method: 'POST' });
    document.cookie = 'session_token=; path=/; expires=Thu, 01 Jan 1970 00:00:00 GMT';
    window.location.href = '/login';
}

// Close modal on outside click
document.addEventListener('click', (e) => {
    if (e.target.classList.contains('modal')) {
        e.target.classList.remove('active');
    }
});

// Close modal on Escape key
document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
        document.querySelectorAll('.modal.active').forEach(modal => {
            modal.classList.remove('active');
        });
    }
});
