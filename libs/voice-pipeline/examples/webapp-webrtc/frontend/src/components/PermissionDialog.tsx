import { Shield, AlertTriangle, Check, X } from 'lucide-react';
import { PermissionRequest } from '../hooks/useAgentState';

interface PermissionDialogProps {
  request: PermissionRequest;
}

export function PermissionDialog({ request }: PermissionDialogProps) {
  const getLevelInfo = (level: string) => {
    switch (level.toLowerCase()) {
      case 'safe':
        return {
          color: 'text-green-500',
          bg: 'bg-green-500/10',
          icon: Check,
          label: 'Seguro',
        };
      case 'moderate':
        return {
          color: 'text-yellow-500',
          bg: 'bg-yellow-500/10',
          icon: Shield,
          label: 'Moderado',
        };
      case 'sensitive':
        return {
          color: 'text-orange-500',
          bg: 'bg-orange-500/10',
          icon: AlertTriangle,
          label: 'Sensivel',
        };
      case 'dangerous':
        return {
          color: 'text-red-500',
          bg: 'bg-red-500/10',
          icon: AlertTriangle,
          label: 'Perigoso',
        };
      default:
        return {
          color: 'text-gray-500',
          bg: 'bg-gray-500/10',
          icon: Shield,
          label: level,
        };
    }
  };

  const levelInfo = getLevelInfo(request.level);
  const LevelIcon = levelInfo.icon;

  return (
    <div className="modal-backdrop">
      <div className="modal-content">
        {/* Header */}
        <div className="flex items-center gap-3 mb-4">
          <div className={`p-2 rounded-lg ${levelInfo.bg}`}>
            <LevelIcon size={24} className={levelInfo.color} />
          </div>
          <div>
            <h3 className="text-lg font-semibold">Confirmacao Necessaria</h3>
            <p className="text-sm text-gray-400">
              Nivel: <span className={levelInfo.color}>{levelInfo.label}</span>
            </p>
          </div>
        </div>

        {/* Content */}
        <div className="mb-6">
          <p className="text-gray-300 mb-3">
            A ferramenta <strong className="text-primary-400">{request.toolName}</strong> requer sua permissao para executar.
          </p>

          {request.reason && (
            <div className="p-3 bg-gray-700 rounded-lg text-sm text-gray-300">
              <span className="text-gray-500">Motivo: </span>
              {request.reason}
            </div>
          )}
        </div>

        {/* Actions */}
        <div className="flex gap-3">
          <button
            onClick={request.onDeny}
            className="btn btn-secondary flex-1"
          >
            <X size={18} />
            Negar
          </button>
          <button
            onClick={request.onApprove}
            className="btn btn-primary flex-1"
          >
            <Check size={18} />
            Permitir
          </button>
        </div>

        {/* Warning for dangerous */}
        {request.level.toLowerCase() === 'dangerous' && (
          <div className="mt-4 p-3 bg-red-500/10 border border-red-500/30 rounded-lg text-sm text-red-400">
            <AlertTriangle size={16} className="inline mr-2" />
            Esta operacao pode ter efeitos irreversiveis. Confirme com cuidado.
          </div>
        )}
      </div>
    </div>
  );
}
