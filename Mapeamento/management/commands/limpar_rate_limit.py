"""Limpa as janelas vencidas do rate limiting.

O `excedeu_limite()` já apaga as janelas antigas de uma chave de vez em
quando (1 em cada 50 chamadas), então este comando não é necessário para o
funcionamento — é para quem quiser zerar a conta na mão sem esperar o sweep,
ou para uma tarefa agendada em produção.
"""

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from Mapeamento.models import TentativaRateLimit
from Mapeamento.ratelimit import IDADE_MAXIMA_JANELAS


class Command(BaseCommand):
    help = 'Remove as janelas de rate limit que já venceram.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--tudo', action='store_true',
            help='Apaga TODAS as janelas, inclusive as que ainda estão valendo.',
        )
        parser.add_argument(
            '--idade', type=int, default=IDADE_MAXIMA_JANELAS,
            help=f'Segundos de idade para considerar a janela vencida '
                 f'(padrão: {IDADE_MAXIMA_JANELAS}s = 24h).',
        )

    def handle(self, *args, **opcoes):
        if opcoes['tudo']:
            total, _detalhes = TentativaRateLimit.objects.all().delete()
            self.stdout.write(self.style.WARNING(
                f'Janelas apagadas: {total} (TODAS, incluindo as válidas).'
            ))
            return

        limite = timezone.now() - timedelta(seconds=opcoes['idade'])
        vencidas = TentativaRateLimit.objects.filter(janela_inicio__lt=limite)
        total, _detalhes = vencidas.delete()

        self.stdout.write(self.style.SUCCESS(
            f'Janelas vencidas (com mais de {opcoes["idade"]}s) apagadas: {total}'
        ))
        self.stdout.write(
            f'Permanecem {TentativaRateLimit.objects.count()} registro(s).'
        )