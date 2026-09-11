/** @odoo-module **/

const DB_NAME = "CotizadorOfflineDB";
const DB_VERSION = 1;

class CotizadorOfflineDB {
    constructor() {
        this.db = null;
    }

    async getDB() {
        if (this.db) return this.db;

        return new Promise((resolve, reject) => {
            const request = window.indexedDB.open(DB_NAME, DB_VERSION);

            request.onupgradeneeded = (event) => {
                const db = event.target.result;

                // 1. Catálogo completo (modelos, matrices, accesorios, planes)
                if (!db.objectStoreNames.contains("catalog")) {
                    db.createObjectStore("catalog", { keyPath: "key" });
                }

                // 2. Clientes cacheados
                if (!db.objectStoreNames.contains("partners")) {
                    const partnerStore = db.createObjectStore("partners", { keyPath: "id" });
                    partnerStore.createIndex("name", "name", { unique: false });
                    partnerStore.createIndex("vat", "vat", { unique: false });
                }

                // 3. Cotizaciones guardadas localmente
                if (!db.objectStoreNames.contains("quotes")) {
                    const quoteStore = db.createObjectStore("quotes", { keyPath: "uuid" });
                    quoteStore.createIndex("status", "status", { unique: false });
                    quoteStore.createIndex("created_at", "created_at", { unique: false });
                }

                // 4. Metadatos (versión, fecha sincronización)
                if (!db.objectStoreNames.contains("meta")) {
                    db.createObjectStore("meta", { keyPath: "key" });
                }
            };

            request.onsuccess = (event) => {
                this.db = event.target.result;
                resolve(this.db);
            };

            request.onerror = (event) => {
                console.error("Error al abrir IndexedDB:", event.target.error);
                reject(event.target.error);
            };
        });
    }

    // --- Catálogo ---

    async saveCatalogPackage(pkg) {
        const db = await this.getDB();
        return new Promise((resolve, reject) => {
            const tx = db.transaction(["catalog", "meta"], "readwrite");
            const catStore = tx.objectStore("catalog");
            const metaStore = tx.objectStore("meta");

            catStore.put({ key: "current_package", data: pkg });
            metaStore.put({ key: "last_sync", timestamp: new Date().toISOString() });

            tx.oncomplete = () => resolve(true);
            tx.onerror = (e) => reject(e.target.error);
        });
    }

    async getCatalogPackage() {
        const db = await this.getDB();
        return new Promise((resolve, reject) => {
            const tx = db.transaction(["catalog"], "readonly");
            const store = tx.objectStore("catalog");
            const request = store.get("current_package");

            request.onsuccess = () => resolve(request.result ? request.result.data : null);
            request.onerror = (e) => reject(e.target.error);
        });
    }

    async getLastSyncDate() {
        const db = await this.getDB();
        return new Promise((resolve, reject) => {
            const tx = db.transaction(["meta"], "readonly");
            const store = tx.objectStore("meta");
            const request = store.get("last_sync");

            request.onsuccess = () => resolve(request.result ? request.result.timestamp : null);
            request.onerror = (e) => reject(e.target.error);
        });
    }

    // --- Clientes ---

    async savePartners(partnersList) {
        const db = await this.getDB();
        return new Promise((resolve, reject) => {
            const tx = db.transaction(["partners"], "readwrite");
            const store = tx.objectStore("partners");

            for (const p of partnersList) {
                store.put(p);
            }

            tx.oncomplete = () => resolve(true);
            tx.onerror = (e) => reject(e.target.error);
        });
    }

    async searchPartners(query = "") {
        const db = await this.getDB();
        return new Promise((resolve, reject) => {
            const tx = db.transaction(["partners"], "readonly");
            const store = tx.objectStore("partners");
            const request = store.getAll();

            request.onsuccess = () => {
                const all = request.result || [];
                const q = query.trim().toLowerCase();
                if (!q) return resolve(all.slice(0, 50));

                const filtered = all.filter(
                    (p) =>
                        (p.name && p.name.toLowerCase().includes(q)) ||
                        (p.vat && p.vat.toLowerCase().includes(q)) ||
                        (p.phone && p.phone.includes(q))
                );
                resolve(filtered.slice(0, 50));
            };
            request.onerror = (e) => reject(e.target.error);
        });
    }

    // --- Cotizaciones Offline ---

    async saveOfflineQuote(quote) {
        const db = await this.getDB();
        return new Promise((resolve, reject) => {
            const tx = db.transaction(["quotes"], "readwrite");
            const store = tx.objectStore("quotes");

            // Asegurar campos base
            if (!quote.uuid) {
                quote.uuid = "OFF-" + Date.now().toString(36).toUpperCase() + "-" + Math.random().toString(36).substring(2, 6).toUpperCase();
            }
            if (!quote.created_at) {
                quote.created_at = new Date().toISOString();
            }
            if (!quote.status) {
                quote.status = "pending"; // 'pending' | 'synced'
            }

            store.put(quote);

            tx.oncomplete = () => resolve(quote);
            tx.onerror = (e) => reject(e.target.error);
        });
    }

    async getAllQuotes() {
        const db = await this.getDB();
        return new Promise((resolve, reject) => {
            const tx = db.transaction(["quotes"], "readonly");
            const store = tx.objectStore("quotes");
            const request = store.getAll();

            request.onsuccess = () => {
                const list = request.result || [];
                list.sort((a, b) => new Date(b.created_at) - new Date(a.created_at));
                resolve(list);
            };
            request.onerror = (e) => reject(e.target.error);
        });
    }

    async getPendingQuotes() {
        const all = await this.getAllQuotes();
        return all.filter((q) => q.status === "pending");
    }

    async markQuoteSynced(uuid, orderId, orderName) {
        const db = await this.getDB();
        return new Promise((resolve, reject) => {
            const tx = db.transaction(["quotes"], "readwrite");
            const store = tx.objectStore("quotes");
            const getReq = store.get(uuid);

            getReq.onsuccess = () => {
                const quote = getReq.result;
                if (!quote) return resolve(false);

                quote.status = "synced";
                quote.order_id = orderId;
                quote.order_name = orderName;
                quote.synced_at = new Date().toISOString();

                store.put(quote);
            };

            tx.oncomplete = () => resolve(true);
            tx.onerror = (e) => reject(e.target.error);
        });
    }

    async deleteQuote(uuid) {
        const db = await this.getDB();
        return new Promise((resolve, reject) => {
            const tx = db.transaction(["quotes"], "readwrite");
            const store = tx.objectStore("quotes");
            store.delete(uuid);
            tx.oncomplete = () => resolve(true);
            tx.onerror = (e) => reject(e.target.error);
        });
    }
}

export const offlineDB = new CotizadorOfflineDB();
