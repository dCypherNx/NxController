# Nx Controller

Integração para Home Assistant que se conecta ao controlador via SSH, descobre as interfaces de rede e monitora os dispositivos conectados.

## Instalação
1. Copie a pasta `custom_components/nx_controller` para o diretório `custom_components` do seu Home Assistant.
2. Reinicie o Home Assistant.

## Configuração
1. Acesse **Configurações → Dispositivos e Serviços → Adicionar Integração** e escolha **Nx Controller**.
2. Informe o IP do roteador/AP, o usuário e a senha SSH.
3. O assistente validará a conexão via SSH e criará o dispositivo no Home Assistant.

Após configurado, a integração coleta as interfaces de rede do controlador e lista os dispositivos conectados, criando sensores para cada um deles.
