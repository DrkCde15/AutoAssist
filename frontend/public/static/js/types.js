// @ts-check
/**
 * @module AutoAssistTypes
 * Type definitions for AutoAssist frontend (JSDoc - zero build step)
 */

/**
 * @typedef {Object} User
 * @property {number} id
 * @property {string} nome
 * @property {string} email
 * @property {boolean} is_premium
 * @property {string} created_at
 * @property {boolean} possui_veiculo
 * @property {boolean} trial_expired
 * @property {number} trial_days_remaining
 * @property {Vehicle[]} veiculos
 * @property {number} total_consultas
 * @property {boolean} is_two_factor_enabled
 * @property {boolean} maintenance_email_enabled
 * @property {string|null} maintenance_email_last_sent
 */

/**
 * @typedef {Object} Vehicle
 * @property {number} id
 * @property {string} tipo
 * @property {string} marca
 * @property {string} modelo
 * @property {number|null} ano_fabricacao
 * @property {number|null} ano_compra
 * @property {number|null} quilometragem
 * @property {string|null} [fipe_valor]
 * @property {string|null} [fipe_mes_referencia]
 */

/**
 * @typedef {Object} ChatMessage
 * @property {number} [id]
 * @property {string} [session_id]
 * @property {string} mensagem_usuario
 * @property {string} [resposta_ia]
 * @property {string} created_at
 * @property {Array} [videos]
 * @property {Array} [links]
 * @property {string} [topic]
 * @property {Array} [attachments]
 */

/**
 * @typedef {Object} ChatResponse
 * @property {number} id
 * @property {string} session_id
 * @property {string} mensagem_usuario
 * @property {string} resposta_ia
 * @property {string} created_at
 * @property {VideoInfo[]} videos
 * @property {LinkInfo[]} links
 * @property {string} topic
 * @property {AttachmentInfo[]} attachments
 */

/**
 * @typedef {Object} VideoInfo
 * @property {string} titulo
 * @property {string} url
 * @property {string} thumbnail
 * @property {string} canal
 */

/**
 * @typedef {Object} LinkInfo
 * @property {string} titulo
 * @property {string} url
 * @property {string} tipo
 * @property {string} icon
 */

/**
 * @typedef {Object} AttachmentInfo
 * @property {string} name
 * @property {string} type
 * @property {number} size
 */

/**
 * @typedef {Object} DashboardData
 * @property {Vehicle} veiculo
 * @property {{Valor: string, MesReferencia: string}} fipe
 * @property {AlertInfo[]} saude
 * @property {Object} predicao
 * @property {{manutencoes_realizadas: number, data_ultima_manutencao: string, chats_realizados: number, health_score: number}} estatisticas_extras
 */

/**
 * @typedef {Object} AlertInfo
 * @property {string} item
 * @property {string} msg
 * @property {string} status
 */

/**
 * @typedef {Object} MaintenanceRecord
 * @property {number} id
 * @property {number} user_id
 * @property {number|null} vehicle_id
 * @property {string} description
 * @property {string} maintenance_type
 * @property {string} maintenance_label
 * @property {string} service_date
 * @property {number|null} service_km
 * @property {number|null} cost
 * @property {string} currency
 * @property {number|null} interval_days
 * @property {number|null} interval_km
 * @property {string|null} next_due_date
 * @property {number|null} next_due_km
 * @property {Object|null} parser_metadata
 * @property {string} created_at
 */

/**
 * @typedef {Object} FeedbackData
 * @property {number} [id]
 * @property {string} nome
 * @property {string} email
 * @property {number} estrelas
 * @property {string} comentario
 */

/**
 * @typedef {Object} ApiError
 * @property {string} error
 * @property {string} [code]
 */

/**
 * @typedef {'user' | 'model' | 'system'} MessageRole
 */

/**
 * @typedef {Object} HistoryEntry
 * @property {MessageRole} role
 * @property {string} content
 */

/**
 * @typedef {Object} Config
 * @property {string} API_URL
 */

/** @type {Config} */
var CONFIG;

/** @type {typeof import('./auth.js')} */
var Auth;

export {};
