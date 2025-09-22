"""
Intégration API YouTube Captions pour upload automatique de sous-titres
"""

import logging
from pathlib import Path
from typing import Optional, Dict, Any, List
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from googleapiclient.errors import HttpError
import json

log = logging.getLogger(__name__)

class CaptionsError(Exception):
    """Erreur lors de l'upload de sous-titres"""
    pass

# Mapping des codes de langue pour YouTube
YOUTUBE_LANGUAGE_CODES = {
    'fr': 'fr',
    'en': 'en',
    'es': 'es', 
    'de': 'de',
    'it': 'it',
    'pt': 'pt',
    'ru': 'ru',
    'ja': 'ja',
    'ko': 'ko',
    'zh': 'zh-CN',
    'ar': 'ar',
    'hi': 'hi',
    'nl': 'nl',
    'sv': 'sv',
    'no': 'no',
    'da': 'da',
    'fi': 'fi',
    'pl': 'pl',
    'tr': 'tr',
    'th': 'th',
    'vi': 'vi'
}

def build_youtube_service(credentials):
    """Construit le service YouTube API v3"""
    return build('youtube', 'v3', credentials=credentials)

def upload_caption(
    credentials,
    video_id: str,
    srt_path: Path,
    language: str = 'fr',
    name: Optional[str] = None,
    is_draft: bool = False,
    is_auto_synced: bool = False
) -> Dict[str, Any]:
    """
    Upload un fichier de sous-titres vers YouTube
    
    Args:
        credentials: Credentials Google API
        video_id: ID de la vidéo YouTube
        srt_path: Chemin vers le fichier .srt
        language: Code langue (ex: 'fr', 'en')
        name: Nom des sous-titres (optionnel)
        is_draft: Si True, upload en brouillon
        is_auto_synced: Si True, YouTube synchronise automatiquement
        
    Returns:
        Réponse de l'API YouTube
    """
    if not srt_path.exists():
        raise CaptionsError(f"Fichier SRT introuvable: {srt_path}")
    
    # Valider le code de langue
    youtube_lang = YOUTUBE_LANGUAGE_CODES.get(language, language)
    
    try:
        youtube = build_youtube_service(credentials)
        
        # Préparer les métadonnées des sous-titres
        caption_metadata = {
            'snippet': {
                'videoId': video_id,
                'language': youtube_lang,
                'name': name or f"Sous-titres {language.upper()}",
                'isDraft': is_draft,
                'isAutoSynced': is_auto_synced
            }
        }
        
        # Upload du fichier
        media = MediaFileUpload(
            str(srt_path),
            mimetype='application/octet-stream',
            resumable=True
        )
        
        log.info("Upload sous-titres %s pour vidéo %s", language, video_id)
        
        request = youtube.captions().insert(
            part='snippet',
            body=caption_metadata,
            media_body=media
        )
        
        response = request.execute()
        
        log.info("Sous-titres uploadés avec succès: %s", response.get('id'))
        return response
        
    except HttpError as e:
        error_details = json.loads(e.content.decode('utf-8'))
        error_message = error_details.get('error', {}).get('message', str(e))
        raise CaptionsError(f"Erreur API YouTube captions: {error_message}")
    except Exception as e:
        raise CaptionsError(f"Erreur upload sous-titres: {e}")

def list_captions(credentials, video_id: str) -> List[Dict[str, Any]]:
    """
    Liste les sous-titres existants d'une vidéo
    
    Args:
        credentials: Credentials Google API
        video_id: ID de la vidéo YouTube
        
    Returns:
        Liste des sous-titres existants
    """
    try:
        youtube = build_youtube_service(credentials)
        
        request = youtube.captions().list(
            part='snippet',
            videoId=video_id
        )
        
        response = request.execute()
        return response.get('items', [])
        
    except HttpError as e:
        error_details = json.loads(e.content.decode('utf-8'))
        error_message = error_details.get('error', {}).get('message', str(e))
        log.error("Erreur listage captions: %s", error_message)
        return []
    except Exception as e:
        log.error("Erreur listage captions: %s", e)
        return []

def delete_caption(credentials, caption_id: str) -> bool:
    """
    Supprime des sous-titres
    
    Args:
        credentials: Credentials Google API
        caption_id: ID des sous-titres à supprimer
        
    Returns:
        True si suppression réussie
    """
    try:
        youtube = build_youtube_service(credentials)
        
        youtube.captions().delete(id=caption_id).execute()
        log.info("Sous-titres supprimés: %s", caption_id)
        return True
        
    except HttpError as e:
        error_details = json.loads(e.content.decode('utf-8'))
        error_message = error_details.get('error', {}).get('message', str(e))
        log.error("Erreur suppression captions: %s", error_message)
        return False
    except Exception as e:
        log.error("Erreur suppression captions: %s", e)
        return False

def update_caption(
    credentials,
    caption_id: str,
    srt_path: Path,
    name: Optional[str] = None,
    is_draft: bool = False
) -> Dict[str, Any]:
    """
    Met à jour des sous-titres existants
    
    Args:
        credentials: Credentials Google API
        caption_id: ID des sous-titres à mettre à jour
        srt_path: Nouveau fichier .srt
        name: Nouveau nom (optionnel)
        is_draft: Statut brouillon
        
    Returns:
        Réponse de l'API YouTube
    """
    if not srt_path.exists():
        raise CaptionsError(f"Fichier SRT introuvable: {srt_path}")
    
    try:
        youtube = build_youtube_service(credentials)
        
        # Récupérer les métadonnées actuelles
        current = youtube.captions().list(
            part='snippet',
            id=caption_id
        ).execute()
        
        if not current.get('items'):
            raise CaptionsError(f"Sous-titres introuvables: {caption_id}")
        
        current_snippet = current['items'][0]['snippet']
        
        # Préparer les nouvelles métadonnées
        updated_metadata = {
            'id': caption_id,
            'snippet': {
                'videoId': current_snippet['videoId'],
                'language': current_snippet['language'],
                'name': name or current_snippet.get('name'),
                'isDraft': is_draft
            }
        }
        
        # Upload du nouveau fichier
        media = MediaFileUpload(
            str(srt_path),
            mimetype='application/octet-stream',
            resumable=True
        )
        
        request = youtube.captions().update(
            part='snippet',
            body=updated_metadata,
            media_body=media
        )
        
        response = request.execute()
        log.info("Sous-titres mis à jour: %s", caption_id)
        return response
        
    except HttpError as e:
        error_details = json.loads(e.content.decode('utf-8'))
        error_message = error_details.get('error', {}).get('message', str(e))
        raise CaptionsError(f"Erreur mise à jour captions: {error_message}")
    except Exception as e:
        raise CaptionsError(f"Erreur mise à jour sous-titres: {e}")

def upload_multiple_captions(
    credentials,
    video_id: str,
    subtitle_files: Dict[str, Path],
    is_draft: bool = False
) -> Dict[str, Any]:
    """
    Upload plusieurs fichiers de sous-titres pour une vidéo
    
    Args:
        credentials: Credentials Google API
        video_id: ID de la vidéo YouTube
        subtitle_files: Dict {langue: chemin_srt}
        is_draft: Upload en brouillon
        
    Returns:
        Dict {langue: réponse_api}
    """
    results = {}
    
    for language, srt_path in subtitle_files.items():
        try:
            response = upload_caption(
                credentials=credentials,
                video_id=video_id,
                srt_path=srt_path,
                language=language,
                name=f"Sous-titres {language.upper()}",
                is_draft=is_draft
            )
            results[language] = {
                'success': True,
                'caption_id': response.get('id'),
                'response': response
            }
            
        except Exception as e:
            log.error("Échec upload sous-titres %s: %s", language, e)
            results[language] = {
                'success': False,
                'error': str(e)
            }
    
    return results

def caption_exists(credentials, video_id: str, language: str) -> Optional[str]:
    """
    Vérifie si des sous-titres existent déjà pour une langue
    
    Args:
        credentials: Credentials Google API
        video_id: ID de la vidéo YouTube
        language: Code langue à vérifier
        
    Returns:
        ID des sous-titres existants ou None
    """
    try:
        captions = list_captions(credentials, video_id)
        youtube_lang = YOUTUBE_LANGUAGE_CODES.get(language, language)
        
        for caption in captions:
            if caption.get('snippet', {}).get('language') == youtube_lang:
                return caption.get('id')
        
        return None
        
    except Exception as e:
        log.error("Erreur vérification captions existants: %s", e)
        return None

def smart_upload_captions(
    credentials,
    video_id: str,
    subtitle_files: Dict[str, Path],
    replace_existing: bool = False,
    is_draft: bool = False
) -> Dict[str, Any]:
    """
    Upload intelligent de sous-titres (évite les doublons)
    
    Args:
        credentials: Credentials Google API
        video_id: ID de la vidéo YouTube
        subtitle_files: Dict {langue: chemin_srt}
        replace_existing: Remplacer les sous-titres existants
        is_draft: Upload en brouillon
        
    Returns:
        Dict {langue: résultat}
    """
    results = {}
    
    for language, srt_path in subtitle_files.items():
        try:
            existing_id = caption_exists(credentials, video_id, language)
            
            if existing_id:
                if replace_existing:
                    # Mettre à jour les sous-titres existants
                    response = update_caption(
                        credentials=credentials,
                        caption_id=existing_id,
                        srt_path=srt_path,
                        is_draft=is_draft
                    )
                    results[language] = {
                        'success': True,
                        'action': 'updated',
                        'caption_id': existing_id,
                        'response': response
                    }
                else:
                    # Ignorer si déjà existant
                    results[language] = {
                        'success': True,
                        'action': 'skipped',
                        'caption_id': existing_id,
                        'message': 'Sous-titres déjà présents'
                    }
            else:
                # Créer nouveaux sous-titres
                response = upload_caption(
                    credentials=credentials,
                    video_id=video_id,
                    srt_path=srt_path,
                    language=language,
                    is_draft=is_draft
                )
                results[language] = {
                    'success': True,
                    'action': 'created',
                    'caption_id': response.get('id'),
                    'response': response
                }
                
        except Exception as e:
            log.error("Échec smart upload sous-titres %s: %s", language, e)
            results[language] = {
                'success': False,
                'error': str(e)
            }
    
    return results
