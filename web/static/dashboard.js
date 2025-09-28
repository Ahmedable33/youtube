// YouTube Automation Monitor - Dashboard JavaScript

class DashboardApp {
    constructor() {
        this.ws = null;
        this.reconnectInterval = null;
        this.isConnected = false;
        this.pendingAction = null;

        this.initializeElements();
        this.setupEventListeners();
        this.connectWebSocket();
    }

    initializeElements() {
        // Status elements
        this.connectionStatus = document.getElementById('connection-status');
        this.pendingCount = document.getElementById('pending-count');
        this.successRate = document.getElementById('success-rate');
        this.recentCount = document.getElementById('recent-count');
        this.archivedCount = document.getElementById('archived-count');

        // Task lists
        this.pendingTasks = document.getElementById('pending-tasks');
        this.archivedTasks = document.getElementById('archived-tasks');

        // Buttons
        this.refreshBtn = document.getElementById('refresh-btn');
        this.loadHistoryBtn = document.getElementById('load-history-btn');

        // Modal
        this.modal = document.getElementById('confirm-modal');
        this.modalTitle = document.getElementById('modal-title');
        this.modalMessage = document.getElementById('modal-message');
        this.modalCancel = document.getElementById('modal-cancel');
        this.modalConfirm = document.getElementById('modal-confirm');
    }

    setupEventListeners() {
        this.refreshBtn.addEventListener('click', () => this.refreshData());
        this.loadHistoryBtn.addEventListener('click', () => this.loadHistory());

        // Modal events
        this.modalCancel.addEventListener('click', () => this.hideModal());
        this.modalConfirm.addEventListener('click', () => this.confirmAction());

        // Close modal on background click
        this.modal.addEventListener('click', (e) => {
            if (e.target === this.modal) {
                this.hideModal();
            }
        });

        // Keyboard shortcuts
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') {
                this.hideModal();
            } else if (e.key === 'F5' || (e.ctrlKey && e.key === 'r')) {
                e.preventDefault();
                this.refreshData();
            }
        });
    }

    connectWebSocket() {
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const wsUrl = `${protocol}//${window.location.host}/ws`;

        try {
            this.ws = new WebSocket(wsUrl);

            this.ws.onopen = () => {
                console.log('WebSocket connecté');
                this.isConnected = true;
                this.updateConnectionStatus(true);

                if (this.reconnectInterval) {
                    clearInterval(this.reconnectInterval);
                    this.reconnectInterval = null;
                }
            };

            this.ws.onmessage = (event) => {
                const data = JSON.parse(event.data);
                this.handleWebSocketMessage(data);
            };

            this.ws.onclose = () => {
                console.log('WebSocket fermé');
                this.isConnected = false;
                this.updateConnectionStatus(false);
                this.scheduleReconnect();
            };

            this.ws.onerror = (error) => {
                console.error('Erreur WebSocket:', error);
                this.isConnected = false;
                this.updateConnectionStatus(false);
            };

        } catch (error) {
            console.error('Impossible de se connecter au WebSocket:', error);
            this.scheduleReconnect();
        }
    }

    scheduleReconnect() {
        if (this.reconnectInterval) return;

        this.reconnectInterval = setInterval(() => {
            console.log('Tentative de reconnexion...');
            this.connectWebSocket();
        }, 5000);
    }

    updateConnectionStatus(connected) {
        if (connected) {
            this.connectionStatus.className = 'status-connected';
            this.connectionStatus.innerHTML = '<i class="fas fa-circle"></i> Connecté';
        } else {
            this.connectionStatus.className = 'status-disconnected';
            this.connectionStatus.innerHTML = '<i class="fas fa-circle"></i> Déconnecté';
        }
    }

    handleWebSocketMessage(data) {
        switch (data.type) {
            case 'initial_data':
            case 'update':
                this.updateStats(data.stats);
                this.updatePendingTasks(data.pending_tasks);
                break;

            case 'task_retried':
                this.showNotification('Tâche relancée avec succès', 'success');
                this.refreshData();
                break;

            case 'task_cancelled':
                this.showNotification('Tâche annulée avec succès', 'info');
                this.refreshData();
                break;

            case 'task_deleted':
                this.showNotification('Tâche supprimée avec succès', 'info');
                this.refreshData();
                break;
        }
    }

    updateStats(stats) {
        this.pendingCount.textContent = stats.total_pending || 0;
        this.successRate.textContent = `${stats.success_rate || 0}%`;
        this.recentCount.textContent = stats.recent_24h || 0;
        this.archivedCount.textContent = stats.total_archived || 0;
    }

    updatePendingTasks(tasks) {
        if (!tasks || tasks.length === 0) {
            this.pendingTasks.innerHTML = '<p class="empty-state">Aucune tâche en attente</p>';
            return;
        }

        this.pendingTasks.innerHTML = tasks.map(task => this.renderTask(task, 'pending')).join('');
    }

    renderTask(task, type) {
        const status = task.status || 'unknown';
        const receivedAt = new Date(task.received_at).toLocaleString('fr-FR');
        const videoPath = task.video_path || '';
        const fileName = videoPath.split('/').pop() || 'Fichier inconnu';

        const meta = task.meta || {};
        const title = meta.title || 'Titre non défini';
        const description = meta.description || 'Description non définie';
        const truncatedDesc = description.length > 100 ?
            description.substring(0, 100) + '...' : description;

        const youtubeId = task.youtube_id;
        const youtubeLink = youtubeId ?
            `<a href="https://www.youtube.com/watch?v=${youtubeId}" target="_blank" class="btn btn-small btn-primary">
                <i class="fab fa-youtube"></i> Voir sur YouTube
            </a>` : '';

        const actions = this.renderTaskActions(task, type);

        return `
            <div class="task-item">
                <div class="task-header">
                    <div class="task-info">
                        <h4>${this.escapeHtml(title)}</h4>
                        <span class="task-status status-${status}">${status}</span>
                    </div>
                </div>

                <div class="task-meta">
                    <span><i class="fas fa-file-video"></i> ${this.escapeHtml(fileName)}</span>
                    <span><i class="fas fa-clock"></i> ${receivedAt}</span>
                    ${task.chat_id ? `<span><i class="fas fa-user"></i> Chat ${task.chat_id}</span>` : ''}
                    ${task.youtube_id ? `<span><i class="fab fa-youtube"></i> ${task.youtube_id}</span>` : ''}
                </div>

                <div class="task-description">
                    ${this.escapeHtml(truncatedDesc)}
                </div>

                <div class="task-actions">
                    ${actions}
                    ${youtubeLink}
                </div>
            </div>
        `;
    }

    renderTaskActions(task, type) {
        const fileName = task.file_name;
        const status = task.status;

        if (type === 'pending') {
            if (status === 'pending') {
                return `
                    <button class="btn btn-small btn-danger" onclick="app.cancelTask('${fileName}')">
                        <i class="fas fa-times"></i> Annuler
                    </button>
                `;
            }
            return '';
        } else {
            // Archived tasks
            let actions = '';

            if (status === 'error' || status === 'cancelled') {
                actions += `
                    <button class="btn btn-small btn-success" onclick="app.retryTask('${fileName}')">
                        <i class="fas fa-redo"></i> Relancer
                    </button>
                `;
            }

            actions += `
                <button class="btn btn-small btn-danger" onclick="app.deleteTask('${fileName}')">
                    <i class="fas fa-trash"></i> Supprimer
                </button>
            `;

            return actions;
        }
    }

    async refreshData() {
        this.refreshBtn.disabled = true;
        this.refreshBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Actualisation...';

        try {
            // Refresh stats
            const statsResponse = await fetch('/api/stats');
            const stats = await statsResponse.json();
            this.updateStats(stats);

            // Refresh pending tasks
            const tasksResponse = await fetch('/api/tasks/pending');
            const tasks = await tasksResponse.json();
            this.updatePendingTasks(tasks);

            this.showNotification('Données actualisées', 'success');

        } catch (error) {
            console.error('Erreur lors de l\'actualisation:', error);
            this.showNotification('Erreur lors de l\'actualisation', 'error');
        } finally {
            this.refreshBtn.disabled = false;
            this.refreshBtn.innerHTML = '<i class="fas fa-sync-alt"></i> Actualiser';
        }
    }

    async loadHistory() {
        this.loadHistoryBtn.disabled = true;
        this.loadHistoryBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Chargement...';

        try {
            const response = await fetch('/api/tasks/archived?limit=50');
            const tasks = await response.json();

            if (!tasks || tasks.length === 0) {
                this.archivedTasks.innerHTML = '<p class="empty-state">Aucune tâche archivée</p>';
            } else {
                this.archivedTasks.innerHTML = tasks.map(task => this.renderTask(task, 'archived')).join('');
            }

        } catch (error) {
            console.error('Erreur lors du chargement de l\'historique:', error);
            this.archivedTasks.innerHTML = '<p class="empty-state">Erreur lors du chargement</p>';
            this.showNotification('Erreur lors du chargement de l\'historique', 'error');
        } finally {
            this.loadHistoryBtn.disabled = false;
            this.loadHistoryBtn.innerHTML = '<i class="fas fa-download"></i> Charger l\'historique';
        }
    }

    retryTask(fileName) {
        this.showModal(
            'Relancer la tâche',
            `Êtes-vous sûr de vouloir relancer la tâche "${fileName}" ?`,
            () => this.performAction('retry', fileName)
        );
    }

    cancelTask(fileName) {
        this.showModal(
            'Annuler la tâche',
            `Êtes-vous sûr de vouloir annuler la tâche "${fileName}" ?`,
            () => this.performAction('cancel', fileName)
        );
    }

    deleteTask(fileName) {
        this.showModal(
            'Supprimer la tâche',
            `Êtes-vous sûr de vouloir supprimer définitivement la tâche "${fileName}" ?`,
            () => this.performAction('delete', fileName)
        );
    }

    async performAction(action, fileName) {
        try {
            let url, method;

            switch (action) {
                case 'retry':
                    url = `/api/tasks/${fileName}/retry`;
                    method = 'POST';
                    break;
                case 'cancel':
                    url = `/api/tasks/${fileName}/cancel`;
                    method = 'POST';
                    break;
                case 'delete':
                    url = `/api/tasks/${fileName}`;
                    method = 'DELETE';
                    break;
                default:
                    throw new Error('Action inconnue');
            }

            const response = await fetch(url, { method });
            const result = await response.json();

            if (response.ok) {
                this.showNotification(result.message, 'success');
                // Les mises à jour viendront via WebSocket
            } else {
                throw new Error(result.detail || 'Erreur inconnue');
            }

        } catch (error) {
            console.error(`Erreur lors de l'action ${action}:`, error);
            this.showNotification(`Erreur: ${error.message}`, 'error');
        }
    }

    showModal(title, message, confirmCallback) {
        this.modalTitle.textContent = title;
        this.modalMessage.textContent = message;
        this.pendingAction = confirmCallback;
        this.modal.style.display = 'block';
    }

    hideModal() {
        this.modal.style.display = 'none';
        this.pendingAction = null;
    }

    confirmAction() {
        if (this.pendingAction) {
            this.pendingAction();
            this.hideModal();
        }
    }

    showNotification(message, type = 'info') {
        // Remove existing notifications
        const existing = document.querySelectorAll('.notification');
        existing.forEach(n => n.remove());

        const notification = document.createElement('div');
        notification.className = `notification ${type}`;
        notification.textContent = message;

        document.body.appendChild(notification);

        // Show notification
        setTimeout(() => notification.classList.add('show'), 100);

        // Hide notification after 3 seconds
        setTimeout(() => {
            notification.classList.remove('show');
            setTimeout(() => notification.remove(), 300);
        }, 3000);
    }

    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
}

// Initialize app when DOM is loaded
document.addEventListener('DOMContentLoaded', () => {
    window.app = new DashboardApp();
});
