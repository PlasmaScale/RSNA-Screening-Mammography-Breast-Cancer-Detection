# AUTOGENERATED! DO NOT EDIT! File to edit: preprocess.ipynb.

# %% auto 0
__all__ = ['MammoPreprocessorBase', 'MammoPreprocessorCBISDDSM', 'MammoPreprocessorRSNA']

# %% preprocess.ipynb 2
from fastai.basics import *
from fastai.medical.imaging import *

import numpy as np
import pandas as pd
import cv2
import dicomsdl as dicom
from tqdm.notebook import tqdm, trange
from joblib import Parallel, delayed
import glob

# %% preprocess.ipynb 3
# Base class for preprocessing mammography images
class MammoPreprocessorBase():
    
    def __init__(self, img_path: str, 
                 image_size: tuple=(4096,2048), dir_name: str="Mammography_Dataset"):
        """
        Initializes the object with the path to the images and desired image size. 
        Creates a directory to save preprocessed images if it doesn't exist.
        """
        self.img_path = img_path
        self.image_size = image_size
        if dir_name:
            os.makedirs(f"{dir_name}", exist_ok=True)
            self.save_path = os.path.join(os.getcwd(), dir_name)
        self.images = glob.glob(f"{img_path}/**/*.dcm", recursive=True)
    
    def preprocess_all(self, fformat: str, hist_eq: bool=True, n_jobs: int=-1, save=True):
        """
        Preprocesses all images in parallel. 
        Applies histogram equalization if hist_eq=True, saves images if save=True.
        """
        Parallel(n_jobs=n_jobs) \
            (delayed(self.preprocess_image) \
            (path, fformat, hist_eq, save) for path in tqdm(self.images, total=len(self.images)))
        print("Parallel preprocessing done!")
    
    
    def _hist_eq(self, img):
        # Histogram equalization only works on 8-bit images
        img = self._convert_to_8bit(img)
        return cv2.equalizeHist(img)
    
    def _convert_to_8bit(self,img):
        return (img / img.max()*255).astype(np.uint8)
    
    def _padresize_to_width(self, img, size, mask=None):
        
        h, w  = img.shape
        
        # If the width of the image is less than the desired width
        if w < size[1]:
            # Add padding to the right side of the image to reach the desired width
            img = cv2.copyMakeBorder(img, 0, 0, 0, size[1] - w, cv2.BORDER_CONSTANT, value=(0, 0, 0))
            if mask is not None:
                mask = cv2.copyMakeBorder(mask, 0, 0, 0, size[1] - w, cv2.BORDER_CONSTANT, value=(0, 0, 0))
        
        # If the width of the image is greater than the desired width
        if w > size[1]:
            # Resize the image to the desired width
            img = cv2.resize(img, (size[1], size[0]))
            # Resize the mask if provided with interpolation set to nearest to keep pixel values
            if mask is not None:
                mask = cv2.resize(mask, (size[1], size[0]), interpolation = cv2.INTER_NEAREST)
            
        return (img, mask) if mask is not None else img
    
    # Resize image but keep aspect ratio
    def _resize_to_height(self, img, size, mask=None):
        
        h,w = img.shape
        # Calculate aspect ratio
        r = h/w
        # Resize to desired height and calculate width to keep aspect ratio
        new_size = (int(size[0]/r), size[0])
        
        # cv2.resize takes image size in form (width, height)
        img = cv2.resize(img, new_size)
        if mask is not None:
            # Use nearest interpolation to keep mask pixel values
            mask = cv2.resize(mask, new_size, interpolation = cv2.INTER_NEAREST)
        
        return (img, mask) if mask is not None else img
    
    def _crop_roi(self, img, mask=None):
        
        # Binarize image to remove background noise
        bin_img = self._binarize(img)
        # Find the largest contour
        contour = self._find_contours(bin_img)
        
        # Create a bounding box from the contour
        x1, x2 = np.min(contour[:, :, 0]), np.max(contour[:, :, 0])
        y1, y2 = np.min(contour[:, :, 1]), np.max(contour[:, :, 1])
        
        # Use bounding box coordinates to crop the image and mask if provided
        return (img[y1:y2, x1:x2], mask[y1:y2, x1:x2]) if mask is not None else img[y1:y2, x1:x2] 
        
    def _remove_background(self, img, remove_wlines=False):
        # find a better solution to remove horizontal white lines
        
        # Binarize image to remove noise and find the largest contour
        bin_img = self._binarize(img)
        contour = self._find_contours(bin_img)
        
        # Create a mask from the contour
        mask = np.zeros(bin_img.shape, np.uint8)
        cv2.drawContours(mask, [contour], -1, 255, cv2.FILLED)
        
        # Not working most of the time
        if remove_wlines:
            white_lines_fix = (mask[:,-1]!=255).astype(np.uint8)[:,None]
            mask = (mask * white_lines_fix) / mask.max()
        
        # Multiply the image with the black and white 
        return img * mask
    
    def _find_contours(self, bin_img):
    
        contours, _ = cv2.findContours(bin_img, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
        # Select the largest contour
        contour = max(contours, key=cv2.contourArea)

        return contour
    
    def _binarize(self, img):
        
        # Binarize the image with a 5% threshold
        binarized = (img > (img.max()*0.05)).astype("uint8")
        
        return binarized

    def _correct_side(self, img, mask=None):
        
        # Split image symetrically
        col_sums_split = np.array_split(np.sum(img, axis=0), 2)
        # Sum the pixel values on each side
        left_col_sum = np.sum(col_sums_split[0])
        right_col_sum = np.sum(col_sums_split[1])

        # Determine where the breast is by comparing total pixel values
        if left_col_sum > right_col_sum: 
            return (img, mask) if mask is not None else img
        # Flip if breast on the right
        else: 
            return (np.fliplr(img), np.fliplr(mask)) if mask is not None else np.fliplr(img)

# %% preprocess.ipynb 4
# Class for preprocessing mammography images from CBIS-DDSM
# Inherits most methods from base class
class MammoPreprocessorCBISDDSM(MammoPreprocessorBase):
    
    def __init__(self, img_path: str, masks: str=None, 
               mammo_imgs_csv: str=None, masks_csv: str=None, case_desc_csv: str=None,
              image_size: tuple=(4096,2048), dir_name: str="CBIS_DDSM"):
    
        super().__init__(img_path, image_size, dir_name)
        # Cleaning and merging the datasets that came with the images
        self.df = self._merge_dfs(mammo_imgs_csv, masks_csv, case_desc_csv)
        
    def preprocess_image(self, path:str, fformat: str="png", hist_eq: bool=True, save: bool=True):
        
        # Use dicomsdl to open dcm files (faster than pydicom)
        img = dicom.open(path).pixelData()
        # Each abnormality has a seperate mask so combine then into one for each image
        labels = self._combine_masks(path)
        
        img, labels = super()._correct_side(img, labels)
        img = super()._remove_background(img)
        img, labels = super()._crop_roi(img, labels)
        img, labels = super()._resize_to_height(img, self.image_size, labels)
        img, labels = super()._padresize_to_width(img, self.image_size, labels)
        if hist_eq:
            img = super()._hist_eq(img)
        else:
            img = super()._convert_to_8bit(img)
        
        if save:
            self._save_image(img, path, fformat=fformat, mask=labels)
        else: 
            return img
        
    def _save_image(self, img, path, fformat: str, mask=None):
        """
        Naming convention:
        Mass-Training_P_00001_LEFT_MLO_mammo.png
        
        Lesion type/train or test/patient id/left or right breast/view/mask or image/exstension
        """
        
        dir_path = self._create_save_path(path)
        fname = re.search("/.+/(.+_P_[0-9]+_.+?)/", path).group(1)
        
        fname_img = f"{fname}_mammo.{fformat}"
        save_path = os.path.join(dir_path, fname_img)
        cv2.imwrite(save_path, img)
        
        if mask is not None:
            fname_mask = f"{fname}_mask.png"
            save_path = os.path.join(dir_path, fname_mask)
            cv2.imwrite(save_path, mask)
        
    def _create_save_path(self, img_path):
 
        # Create a folder from patient id    
        patient_folder = re.search("_(P_[0-9]+)_", img_path).group(1)
        
        save_path = os.path.join(self.save_path, patient_folder)
        os.makedirs(save_path, exist_ok=True)
        
        return save_path

    def _combine_masks(self, path):

        image_info = self.df.loc[self.df.full_img_fname==path]

        labels = 0
        for i in range(image_info.shape[0]):
            mask = image_info.iloc[i]
            mask_px = (dicom.open(mask.mask_fname).pixelData() / 255).astype(np.uint8)
            # Mask are coded: 1 for benign, 2 for malignant
            labels += mask_px * mask.pathology

        return labels
    
    def _merge_dfs(self, mammo_imgs_csv, masks_csv, case_desc_csv):
        
        df_full = pd.read_csv(mammo_imgs_csv)
        df_mask = pd.read_csv(masks_csv)
        df_mass = pd.read_csv(case_desc_csv)
        
        mass_type = df_full["PatientID"].str.split("_", n=1)[0][0]
        df_mass["PatientID"] = mass_type + "_" + df_mass.patient_id + "_" + df_mass["left or right breast"] + "_" + df_mass["image view"] + "_" + df_mass["abnormality id"].astype("str")
        df_mask = df_mask.loc[df_mask.SeriesDescription=="ROI mask images",].reset_index(drop=True)
        
        mass_cols_keep = ["PatientID", "pathology"]
        mask_cols_keep = ["PatientID", "fname"]
        full_cols_keep = ["PatientID", "fname"]

        df_mass = df_mass[mass_cols_keep]
        df_mask = df_mask[mask_cols_keep]
        df_full = df_full[full_cols_keep]
        
        df_mass.rename(columns={"PatientID": "PathologyID"}, inplace=True)
        df_mask.rename(columns={"PatientID": "PathologyID", "fname": "mask_fname"}, inplace=True)
        df_full.rename(columns={"PatientID": "ImageID", "fname": "full_img_fname"}, inplace=True)

        df_all = df_mass.merge(df_mask, on="PathologyID")
        df_all["ImageID"] = df_all.PathologyID.str.replace(r"_[0-9]$", "", regex=True)
        df_all = df_all.merge(df_full, on="ImageID", how="left")
        
        df_all["PatientID"] = df_all.PathologyID.str.extract("(P_[0-9]+)_", expand=False)
        df_all["pathology"] = df_all.pathology.str.replace("_.*","", regex=True)
        df_all["pathology"].replace({"BENIGN":1, "MALIGNANT":2}, inplace=True)

        df_all.sort_values(by="PatientID", ignore_index=True, inplace=True)
        
        return df_all

# %% preprocess.ipynb 5
class MammoPreprocessorRSNA(MammoPreprocessorBase):
    
    def __init__(self, img_path: str, 
                 image_size: tuple=(4096,2048), dir_name: str="RSNA"):
    
        super().__init__(img_path, image_size, dir_name)
        
    def preprocess_image(self, path:str, fformat: str="png", hist_eq: bool=True, save=True):
        
        scan, img = self._load_dicom(path)
        
        img = self._fix_photometric_inter(scan, img)
        img = self._windowing(scan, img)
        img = super()._correct_side(img)
        img = super()._remove_background(img)
        img = super()._crop_roi(img)
        img = super()._resize_to_height(img, self.image_size)
        img = super()._padresize_to_width(img, self.image_size)
        if hist_eq:
            img = super()._hist_eq(img)
        else:
            img = super()._convert_to_8bit(img)
        
        if save:
            self._save_image(img, path, fformat=fformat)
        else:
            return img
        
    def _save_image(self, img, path, fformat: str):
        
        dir_path = self._create_save_path(path)
        fname = re.search("/([0-9]+).dcm$", path).group(1)
        
        fname_img = f"{fname}.{fformat}"
        save_path = os.path.join(dir_path, fname_img)
        cv2.imwrite(save_path, img)
    
    # https://dicom.nema.org/medical/dicom/2018b/output/chtml/part03/sect_C.11.2.html
    def _windowing(self, scan, img):
        
        function = scan.VOILUTFunction
        
        if type(scan.WindowWidth) == list:
            center = int(np.mean((scan.WindowCenter)))
            width = scan.WindowWidth[0]
        else:
            center = scan.WindowCenter
            width = scan.WindowWidth
        
        y_range = 2**scan.BitsStored - 1
        
        if function == 'SIGMOID':
            img = y_range / (1 + np.exp(-4 * (img - center) / width))
        
        else: # LINEAR
            
            center -= 0.5
            width -= 1
            
            below = img <= (center - width / 2)
            above = img > (center + width / 2)
            between = np.logical_and(~below, ~above)
            img[below] = 0
            img[above] = y_range
            img[between] = ((img[between] - center) / width + 0.5) * y_range
        
        return img
    
    # https://dicom.nema.org/medical/Dicom/2017c/output/chtml/part03/sect_C.7.6.3.html
    def _fix_photometric_inter(self, scan, img):
        
        # Section C.7.6.3.1.2
        if scan.PhotometricInterpretation == "MONOCHROME1":
            img = img.max() - img
            
        return img
    
    def _create_save_path(self, img_path):
 
        patient_folder = re.search("/([0-9]+)/", img_path).group(1)
        
        save_path = os.path.join(self.save_path, patient_folder)
        os.makedirs(save_path, exist_ok=True)
        
        return save_path
    
    def _load_dicom(self, path: str):
        dcmfile = dicom.open(path)
        return dcmfile, dcmfile.pixelData()
