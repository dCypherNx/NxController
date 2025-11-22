# Nx Controller

Integração para Home Assistant que se conecta ao controlador via SSH, descobre as interfaces de rede e monitora os dispositivos conectados.

## Instalação
1. Copie a pasta `custom_components/nx_controller` para o diretório `custom_components` do seu Home Assistant.
2. Reinicie o Home Assistant.

## Configuração
1. Acesse **Configurações → Dispositivos e Serviços → Adicionar Integração** e escolha **Nx Controller**.
2. Informe um apelido para o roteador/AP, o IP, o usuário e a senha SSH.
3. O assistente validará a conexão via SSH e criará o dispositivo no Home Assistant, usando o apelido para compor o nome de todos os sensores derivados.
4. Caso esse controlador seja o responsável pelo DHCP da rede, marque a opção correspondente. A integração lerá os intervalos a partir do comando `uci show dhcp`. Quando houver mais de um controlador configurado, os demais herdarão as informações de faixa do dispositivo marcado como DHCP.

Após configurado, a integração coleta as interfaces de rede do controlador e lista os dispositivos conectados, criando sensores para cada um deles.
