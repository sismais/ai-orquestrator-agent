import { useEffect, useState } from 'react';
import styles from './SettingsPage.module.css';
import { getAutoCleanupSettings, updateAutoCleanupSettings, AutoCleanupSettings } from '../api/settings';

const SettingsPage = () => {
  const [autoCleanupSettings, setAutoCleanupSettings] = useState<AutoCleanupSettings>({
    enabled: true,
    cleanup_after_minutes: 30,
  });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    loadSettings();
  }, []);

  const loadSettings = async () => {
    try {
      setLoading(true);
      const settings = await getAutoCleanupSettings();
      setAutoCleanupSettings(settings);
      setError(null);
    } catch (err) {
      console.error('Failed to load auto-cleanup settings:', err);
      setError('Falha ao carregar configurações de auto-limpeza');
    } finally {
      setLoading(false);
    }
  };

  const handleUpdateAutoCleanup = async (updates: Partial<AutoCleanupSettings>) => {
    try {
      const updatedSettings = await updateAutoCleanupSettings(updates);
      setAutoCleanupSettings(updatedSettings);
      setError(null);
    } catch (err) {
      console.error('Failed to update auto-cleanup settings:', err);
      setError('Falha ao atualizar configurações');
    }
  };

  return (
    <div className={styles.settingsPage}>
      <div className={styles.settingsHeader}>
        <h1 className={styles.settingsTitle}>Configurações</h1>
        <p className={styles.settingsSubtitle}>
          Gerencie as preferências do Sismais AI Orquestrador
        </p>
      </div>

      <div className={styles.settingsContent}>
        <section className={styles.settingsSection}>
          <h2 className={styles.sectionTitle}>Aparência</h2>
          <div className={styles.settingItem}>
            <div className={styles.settingInfo}>
              <h3 className={styles.settingLabel}>Tema</h3>
              <p className={styles.settingDescription}>
                Atualmente usando o tema Cosmic Dark
              </p>
            </div>
            <div className={styles.settingControl}>
              <span className={styles.themeBadge}>🌌 Cosmic Dark</span>
            </div>
          </div>
        </section>

        <section className={styles.settingsSection}>
          <h2 className={styles.sectionTitle}>Workspace</h2>
          <div className={styles.settingItem}>
            <div className={styles.settingInfo}>
              <h3 className={styles.settingLabel}>Nome do Projeto</h3>
              <p className={styles.settingDescription}>
                Nome exibido no workspace
              </p>
            </div>
            <div className={styles.settingControl}>
              <input
                type="text"
                className={styles.input}
                placeholder="Sismais AI Orquestrador"
                disabled
              />
            </div>
          </div>
        </section>

        <section className={styles.settingsSection}>
          <h2 className={styles.sectionTitle}>AI Assistant</h2>
          <div className={styles.settingItem}>
            <div className={styles.settingInfo}>
              <h3 className={styles.settingLabel}>Status do Chat</h3>
              <p className={styles.settingDescription}>
                Assistente AI disponível para conversas
              </p>
            </div>
            <div className={styles.settingControl}>
              <div className={styles.statusBadge}>
                <div className={styles.statusDot}></div>
                <span>Online</span>
              </div>
            </div>
          </div>
        </section>

        <section className={styles.settingsSection}>
          <h2 className={styles.sectionTitle}>Auto-limpeza de Cards Concluídos</h2>

          {error && (
            <div className={styles.errorMessage}>{error}</div>
          )}

          <div className={styles.settingItem}>
            <div className={styles.settingInfo}>
              <h3 className={styles.settingLabel}>Ativar Auto-limpeza</h3>
              <p className={styles.settingDescription}>
                Mover automaticamente cards de Done para Completed
              </p>
            </div>
            <div className={styles.settingControl}>
              <label className={styles.switchLabel}>
                <input
                  type="checkbox"
                  checked={autoCleanupSettings.enabled}
                  onChange={(e) => handleUpdateAutoCleanup({ enabled: e.target.checked })}
                  disabled={loading}
                  className={styles.checkbox}
                />
                <span className={styles.switchText}>
                  {autoCleanupSettings.enabled ? 'Ativado' : 'Desativado'}
                </span>
              </label>
            </div>
          </div>

          <div className={styles.settingItem}>
            <div className={styles.settingInfo}>
              <h3 className={styles.settingLabel}>Período de Permanência</h3>
              <p className={styles.settingDescription}>
                Cards em Done há mais tempo serão movidos para Completed automaticamente
              </p>
            </div>
            <div className={styles.settingControl}>
              <label className={styles.inputLabel}>
                Mover após
                <input
                  type="number"
                  min="1"
                  max="1440"
                  value={autoCleanupSettings.cleanup_after_minutes}
                  onChange={(e) => {
                    const value = parseInt(e.target.value);
                    if (value >= 1 && value <= 1440) {
                      handleUpdateAutoCleanup({ cleanup_after_minutes: value });
                    }
                  }}
                  disabled={loading}
                  className={styles.input}
                  style={{ width: '80px', marginLeft: '8px', marginRight: '8px' }}
                />
                minutos
              </label>
            </div>
          </div>

          <div className={styles.infoBox}>
            <h4>ℹ️ Sobre a Coluna Completed</h4>
            <ul>
              <li>Mantém histórico completo de todos os cards concluídos</li>
              <li>Cards podem ser visualizados quando necessário</li>
              <li>Não polui a visualização do board ativo</li>
              <li>Cards podem ser arquivados manualmente se desejar</li>
            </ul>
          </div>
        </section>

        <section className={styles.comingSoon}>
          <div className={styles.comingSoonIcon}>🚧</div>
          <h2 className={styles.comingSoonTitle}>Mais Configurações em Breve</h2>
          <p className={styles.comingSoonText}>
            Estamos trabalhando em mais opções de personalização para melhorar sua experiência.
          </p>
        </section>
      </div>
    </div>
  );
};

export default SettingsPage;
