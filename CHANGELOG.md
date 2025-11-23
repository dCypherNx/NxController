# Changelog

## 0.3.0
- Implementa mapeamento persistente de identidades para consolidar dispositivos
  com MAC aleatório em sensores únicos e expõe a lista de MACs pendentes para
  facilitar associações manuais.

## 0.2.8
- Corrige a configuração do HACS para usar o conteúdo do repositório em vez de
  um artefato ZIP, garantindo que a integração apareça corretamente no Home
  Assistant após a instalação.

## 0.2.7
- Incremento de versão para a release 0.2.7.

## 0.2.6
- Dispositivos agora utilizam o primeiro endereço MAC identificado como ID,
  mesmo quando um host name está disponível.

## 0.2.5
- Normalização dos nomes de interfaces retornados pelo controlador para
  evitar sufixes como `@ifX` e permitir que rádios WiFi sejam vinculados
  corretamente.

## 0.2.4
- Incremento de versão para a release 0.2.4.

## 0.2.3
- Incremento de versão para a release 0.2.3 com melhorias nos atributos de
  conexão e retirada de campos de host e MAC conforme solicitado.

## 0.2.2
- Incremento de versão para a release 0.2.2.

## 0.2.1
- Incremento de versão para a release 0.2.1.

## 0.2.0
- Incremento de versão para a release 0.2.0.

## 0.2.0.alpha001
- Incremento de versão para a release 0.2.0.alpha001.

## 0.1.3
- Incremento de versão para a release 0.1.3.

## 0.1.2
- Configuração agora solicita IP, usuário e senha para autenticar via SSH.
- Dispositivos conectados são listados a partir das interfaces do controlador.
- Incremento de versão para a release 0.1.2.

## 0.1.1
- IDs de sensores agora utilizam invariavelmente o endereço MAC reportado pelo
  controlador como identificador único.
- Incremento de versão para a release 0.1.1.

## 0.1.0
- Refatoração do coletor SSH para consolidar dispositivos WiFi e com fio de
  forma determinística e sem perdas.
- IDs de sensores agora incluem a entrada configurada, garantindo estabilidade
  mesmo em ambientes com múltiplos controladores.
- Pipeline de release revisado para gerar tag e publicar artefato sempre que a
  versão é atualizada no CI.
