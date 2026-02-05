#!/usr/bin/env python3
"""
Teste de conexao com Elasticsearch.

Verifica se o ES esta acessivel e cria um documento de teste.

Uso:
    python test_elasticsearch.py [--host http://localhost:9200]
"""

import argparse
import json
import sys
from datetime import datetime

try:
    import requests
except ImportError:
    print("Instale requests: pip install requests")
    sys.exit(1)


def test_cluster_health(host: str) -> bool:
    """Testa saude do cluster."""
    print(f"\n[1/4] Testando cluster health em {host}...")

    try:
        response = requests.get(f"{host}/_cluster/health", timeout=5)
        if response.status_code == 200:
            data = response.json()
            status = data.get("status", "unknown")
            print(f"     Cluster status: {status}")
            print(f"     Nodes: {data.get('number_of_nodes', 0)}")
            return status in ["green", "yellow"]
        else:
            print(f"     ERRO: Status {response.status_code}")
            return False
    except Exception as e:
        print(f"     ERRO: {e}")
        return False


def test_create_index(host: str, index_name: str) -> bool:
    """Testa criacao de indice."""
    print(f"\n[2/4] Testando criacao de indice {index_name}...")

    mapping = {
        "mappings": {
            "properties": {
                "utterance_id": {"type": "keyword"},
                "session_id": {"type": "keyword"},
                "call_id": {"type": "keyword"},
                "text": {
                    "type": "text",
                    "analyzer": "portuguese"
                },
                "timestamp": {"type": "date"},
                "audio_duration_ms": {"type": "integer"},
                "transcription_latency_ms": {"type": "integer"}
            }
        }
    }

    try:
        # Tenta criar (ignora se ja existe)
        response = requests.put(
            f"{host}/{index_name}",
            json=mapping,
            headers={"Content-Type": "application/json"},
            timeout=10
        )

        if response.status_code in [200, 201]:
            print(f"     Indice criado com sucesso!")
            return True
        elif response.status_code == 400 and "already exists" in response.text:
            print(f"     Indice ja existe (OK)")
            return True
        else:
            print(f"     ERRO: {response.status_code} - {response.text[:200]}")
            return False

    except Exception as e:
        print(f"     ERRO: {e}")
        return False


def test_index_document(host: str, index_name: str) -> bool:
    """Testa indexacao de documento."""
    print(f"\n[3/4] Testando indexacao de documento...")

    doc = {
        "utterance_id": "test-utterance-001",
        "session_id": "test-session-001",
        "call_id": "test-call-001",
        "text": "Este e um teste de transcricao em portugues",
        "timestamp": datetime.utcnow().isoformat(),
        "audio_duration_ms": 2500,
        "transcription_latency_ms": 150
    }

    try:
        response = requests.post(
            f"{host}/{index_name}/_doc",
            json=doc,
            headers={"Content-Type": "application/json"},
            timeout=10
        )

        if response.status_code in [200, 201]:
            data = response.json()
            doc_id = data.get("_id", "unknown")
            print(f"     Documento indexado: {doc_id}")
            return True
        else:
            print(f"     ERRO: {response.status_code} - {response.text[:200]}")
            return False

    except Exception as e:
        print(f"     ERRO: {e}")
        return False


def test_search_documents(host: str, index_name: str) -> bool:
    """Testa busca de documentos."""
    print(f"\n[4/4] Testando busca de documentos...")

    query = {
        "query": {
            "match": {
                "text": "teste transcricao"
            }
        }
    }

    try:
        # Refresh para garantir que documento esta indexado
        requests.post(f"{host}/{index_name}/_refresh", timeout=5)

        response = requests.get(
            f"{host}/{index_name}/_search",
            json=query,
            headers={"Content-Type": "application/json"},
            timeout=10
        )

        if response.status_code == 200:
            data = response.json()
            hits = data.get("hits", {}).get("total", {})
            total = hits.get("value", 0) if isinstance(hits, dict) else hits
            print(f"     Documentos encontrados: {total}")

            # Mostra primeiro hit
            results = data.get("hits", {}).get("hits", [])
            if results:
                first = results[0].get("_source", {})
                print(f"     Primeiro resultado: '{first.get('text', '')[:50]}...'")

            return True
        else:
            print(f"     ERRO: {response.status_code}")
            return False

    except Exception as e:
        print(f"     ERRO: {e}")
        return False


def cleanup_test_index(host: str, index_name: str):
    """Remove indice de teste."""
    print(f"\n[Cleanup] Removendo indice de teste...")
    try:
        response = requests.delete(f"{host}/{index_name}", timeout=5)
        if response.status_code in [200, 404]:
            print(f"     Indice removido")
    except Exception as e:
        print(f"     AVISO: {e}")


def main():
    parser = argparse.ArgumentParser(description="Teste do Elasticsearch")
    parser.add_argument(
        "--host",
        default="http://localhost:9200",
        help="URL do Elasticsearch (default: http://localhost:9200)"
    )
    parser.add_argument(
        "--keep-index",
        action="store_true",
        help="Manter indice de teste apos execucao"
    )
    args = parser.parse_args()

    test_index = "voice-transcriptions-test"

    print("=" * 60)
    print("TESTE DO ELASTICSEARCH")
    print("=" * 60)

    results = []

    # Testes
    results.append(("Cluster Health", test_cluster_health(args.host)))

    if results[0][1]:  # Se cluster OK, continua
        results.append(("Create Index", test_create_index(args.host, test_index)))
        results.append(("Index Document", test_index_document(args.host, test_index)))
        results.append(("Search Documents", test_search_documents(args.host, test_index)))

        # Cleanup
        if not args.keep_index:
            cleanup_test_index(args.host, test_index)

    # Resumo
    print("\n" + "=" * 60)
    print("RESUMO DOS TESTES")
    print("=" * 60)

    passed = 0
    for name, success in results:
        status = "PASSOU" if success else "FALHOU"
        symbol = "[OK]" if success else "[X]"
        print(f"  {symbol} {name}: {status}")
        if success:
            passed += 1

    print(f"\nTotal: {passed}/{len(results)} testes passaram")
    print("=" * 60)

    sys.exit(0 if passed == len(results) else 1)


if __name__ == "__main__":
    main()
