import * as ImagePicker from 'expo-image-picker';
import { Image } from 'expo-image';
import { useCallback, useEffect, useRef, useState } from 'react';
import {
  ActivityIndicator,
  Linking,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';

import { AppButton, Card, EmptyState } from '@/components/primitives';
import { Palette, Radius, Spacing } from '@/constants/theme';
import { stripMarkdown } from '@/lib/format';
import type { ChatRecord, LinkItem, VideoItem } from '@/lib/types';
import { useAuth } from '@/context/auth';

type PickedImage = {
  uri: string;
  base64: string;
};

export function ChatScreen() {
  const { request } = useAuth();
  const scrollRef = useRef<ScrollView>(null);
  const [history, setHistory] = useState<ChatRecord[]>([]);
  const [message, setMessage] = useState('');
  const [pickedImage, setPickedImage] = useState<PickedImage | null>(null);
  const [loading, setLoading] = useState(false);
  const [loadingHistory, setLoadingHistory] = useState(true);
  const [error, setError] = useState('');

  const loadHistory = useCallback(async () => {
    setLoadingHistory(true);
    try {
      const data = await request<{ chats: ChatRecord[] }>('/api/chat/history');
      setHistory((data.chats || []).slice(-20));
    } catch {
      setHistory([]);
    } finally {
      setLoadingHistory(false);
    }
  }, [request]);

  useEffect(() => {
    const timer = setTimeout(() => {
      void loadHistory();
    }, 0);
    return () => clearTimeout(timer);
  }, [loadHistory]);

  useEffect(() => {
    scrollRef.current?.scrollToEnd({ animated: true });
  }, [history, loading]);

  async function pickImage() {
    setError('');
    const permission = await ImagePicker.requestMediaLibraryPermissionsAsync();
    if (!permission.granted) {
      setError('Permissao para acessar imagens negada.');
      return;
    }

    const result = await ImagePicker.launchImageLibraryAsync({
      mediaTypes: ['images'],
      quality: 0.75,
      base64: true,
      allowsEditing: false,
    });

    if (!result.canceled && result.assets[0]?.base64) {
      setPickedImage({
        uri: result.assets[0].uri,
        base64: `data:image/jpeg;base64,${result.assets[0].base64}`,
      });
    }
  }

  async function send() {
    const trimmed = message.trim();
    if (!trimmed && !pickedImage) return;
    setError('');
    setLoading(true);

    const optimistic: ChatRecord = {
      mensagem_usuario: trimmed || 'Imagem anexada',
      resposta_ia: 'Analisando...',
      created_at: new Date().toISOString(),
    };
    setHistory((items) => [...items, optimistic]);

    try {
      const response = await request<{
        response: string;
        videos: VideoItem[];
        links: LinkItem[];
        chat: ChatRecord;
      }>('/api/chat', {
        method: 'POST',
        body: {
          message: trimmed,
          image: pickedImage?.base64,
          ignore_global_history: false,
        },
      });

      setHistory((items) => [...items.slice(0, -1), response.chat]);
      setMessage('');
      setPickedImage(null);
    } catch (sendError) {
      setHistory((items) => items.slice(0, -1));
      setError(sendError instanceof Error ? sendError.message : 'Nao foi possivel enviar a consulta.');
    } finally {
      setLoading(false);
    }
  }

  return (
    <View style={styles.root}>
      <ScrollView
        ref={scrollRef}
        contentContainerStyle={styles.messages}
        keyboardShouldPersistTaps="handled">
        <Card style={styles.intro}>
          <Text style={styles.title}>Consultor NOG</Text>
          <Text style={styles.muted}>
            Pergunte sobre sintomas, compra, manutencao ou envie uma foto para o Raio-X mecanico.
          </Text>
        </Card>

        {loadingHistory ? (
          <ActivityIndicator color={Palette.primary} />
        ) : history.length ? (
          history.map((chat, index) => <ChatBubble key={`${chat.id || index}`} chat={chat} />)
        ) : (
          <EmptyState title="Sem conversas ainda" body="Mande sua primeira pergunta para iniciar o diagnostico." />
        )}
      </ScrollView>

      {error ? <Text style={styles.error}>{error}</Text> : null}

      {pickedImage ? (
        <View style={styles.previewRow}>
          <Image source={{ uri: pickedImage.uri }} style={styles.previewImage} />
          <Text style={styles.previewText}>Imagem pronta para analise</Text>
          <Pressable onPress={() => setPickedImage(null)} style={styles.removeImage}>
            <Text style={styles.removeImageText}>Remover</Text>
          </Pressable>
        </View>
      ) : null}

      <View style={styles.composer}>
        <Pressable onPress={pickImage} style={styles.iconButton}>
          <Text style={styles.iconButtonText}>+</Text>
        </Pressable>
        <TextInput
          value={message}
          onChangeText={setMessage}
          placeholder="Descreva o problema do carro"
          placeholderTextColor={Palette.textSoft}
          multiline
          style={styles.input}
        />
        <AppButton title="Enviar" onPress={send} loading={loading} disabled={!message.trim() && !pickedImage} />
      </View>
    </View>
  );
}

function ChatBubble({ chat }: { chat: ChatRecord }) {
  return (
    <View style={styles.chatBlock}>
      <View style={styles.userBubble}>
        <Text style={styles.userText}>{chat.mensagem_usuario}</Text>
      </View>
      <View style={styles.botBubble}>
        <Text style={styles.botText}>{stripMarkdown(chat.resposta_ia || '')}</Text>
        <AttachmentList videos={chat.videos || []} links={chat.links || []} />
      </View>
    </View>
  );
}

function AttachmentList({ videos, links }: { videos: VideoItem[]; links: LinkItem[] }) {
  const items = [
    ...videos.map((item) => ({ title: item.titulo || 'Video recomendado', url: item.url })),
    ...links.map((item) => ({ title: item.titulo || 'Link recomendado', url: item.url })),
  ].filter((item) => item.url);

  if (!items.length) return null;

  return (
    <View style={styles.attachments}>
      {items.slice(0, 4).map((item, index) => (
        <Pressable
          key={`${item.url}-${index}`}
          onPress={() => item.url && Linking.openURL(item.url)}
          style={styles.attachmentButton}>
          <Text style={styles.attachmentText}>{item.title}</Text>
        </Pressable>
      ))}
    </View>
  );
}

const styles = StyleSheet.create({
  root: {
    flex: 1,
  },
  messages: {
    padding: Spacing.three,
    gap: Spacing.three,
  },
  intro: {
    gap: Spacing.one,
  },
  title: {
    color: Palette.text,
    fontSize: 20,
    fontWeight: '900',
  },
  muted: {
    color: Palette.textMuted,
    lineHeight: 20,
  },
  chatBlock: {
    gap: Spacing.one,
  },
  userBubble: {
    alignSelf: 'flex-end',
    maxWidth: '88%',
    backgroundColor: Palette.primary,
    borderRadius: Radius.md,
    padding: Spacing.three,
  },
  userText: {
    color: Palette.white,
    lineHeight: 20,
  },
  botBubble: {
    alignSelf: 'flex-start',
    maxWidth: '92%',
    backgroundColor: Palette.surface,
    borderRadius: Radius.md,
    borderWidth: 1,
    borderColor: Palette.border,
    padding: Spacing.three,
    gap: Spacing.two,
  },
  botText: {
    color: Palette.text,
    lineHeight: 21,
  },
  attachments: {
    gap: Spacing.one,
  },
  attachmentButton: {
    borderWidth: 1,
    borderColor: Palette.border,
    borderRadius: Radius.sm,
    padding: Spacing.two,
    backgroundColor: Palette.bgAlt,
  },
  attachmentText: {
    color: Palette.blue,
    fontWeight: '700',
  },
  error: {
    color: Palette.red,
    paddingHorizontal: Spacing.three,
    paddingBottom: Spacing.one,
  },
  previewRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: Spacing.two,
    paddingHorizontal: Spacing.three,
    paddingVertical: Spacing.two,
    borderTopWidth: 1,
    borderTopColor: Palette.border,
    backgroundColor: Palette.surface,
  },
  previewImage: {
    width: 44,
    height: 44,
    borderRadius: Radius.sm,
  },
  previewText: {
    flex: 1,
    color: Palette.text,
    fontWeight: '700',
  },
  removeImage: {
    padding: Spacing.two,
  },
  removeImageText: {
    color: Palette.red,
    fontWeight: '800',
  },
  composer: {
    flexDirection: 'row',
    alignItems: 'flex-end',
    gap: Spacing.two,
    padding: Spacing.two,
    borderTopWidth: 1,
    borderTopColor: Palette.border,
    backgroundColor: Palette.surface,
  },
  iconButton: {
    width: 48,
    height: 48,
    borderRadius: Radius.md,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: Palette.bgAlt,
    borderWidth: 1,
    borderColor: Palette.border,
  },
  iconButtonText: {
    color: Palette.text,
    fontSize: 24,
    fontWeight: '900',
  },
  input: {
    flex: 1,
    minHeight: 48,
    maxHeight: 116,
    borderRadius: Radius.md,
    borderWidth: 1,
    borderColor: Palette.border,
    backgroundColor: Palette.bg,
    color: Palette.text,
    paddingHorizontal: Spacing.three,
    paddingVertical: 12,
    fontSize: 15,
  },
});
